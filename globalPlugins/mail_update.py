# -*- coding: utf-8 -*-
# NVDA bağımsız güncelleme motoru.
# Telif Hakkı (C) 2026 Mehmet Aykurt
# URL: https://github.com/MehmetAykurt/engelsiz-mail

import hashlib
import json
import os
import ssl
import tempfile
import threading
import urllib.parse
import urllib.request

import addonHandler
import globalPluginHandler
import gui
import logHandler
import ui
import wx


KONTROL_GECIKMESI_MS = 7000
BAGLANTI_ZAMAN_ASIMI = 10
INDIRME_ZAMAN_ASIMI = 30
AZAMI_JSON_BOYUTU = 1024 * 1024
AZAMI_EKLENTI_BOYUTU = 150 * 1024 * 1024

GUNLUK_AKTIF = False
GUNLUK_ON_EKI = "NVDA güncelleme motoru: "

KULLANICI_ARACISI = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "NVDA-Official-Update-Engine/1.0.0"
)

_guncelleme_penceresi_acik = False
_indirme_basladi = False
_durum_kilidi = threading.RLock()
_manifest_yolu_onbellek = None
_manifest_yolu_arandi = False


def gunluk_yaz(metin):
    if not GUNLUK_AKTIF:
        return

    try:
        logHandler.log.info(GUNLUK_ON_EKI + str(metin))
    except Exception:
        pass


def ssl_baglami_olustur():
    try:
        baglam = ssl.create_default_context()

        if hasattr(ssl, "VERIFY_X509_STRICT"):
            try:
                baglam.verify_flags &= ~ssl.VERIFY_X509_STRICT
            except Exception:
                pass

        return baglam

    except Exception:
        return None


def metin_uret(kodlar):
    try:
        return "".join(chr(kod) for kod in kodlar)
    except Exception:
        return ""


RESMI_AD_SOYAD = metin_uret((77, 101, 104, 109, 101, 116, 32, 65, 121, 107, 117, 114, 116))
RESMI_EPOSTA = metin_uret((109, 46, 97, 121, 107, 117, 114, 116, 51, 56, 64, 103, 109, 97, 105, 108, 46, 99, 111, 109))
RESMI_GITHUB_KULLANICI_ADI = metin_uret((77, 101, 104, 109, 101, 116, 65, 121, 107, 117, 114, 116))
RESMI_GITHUB_KULLANICI_ADI_KUCUK = RESMI_GITHUB_KULLANICI_ADI.lower()

GITHUB_ALAN_ADI = metin_uret((103, 105, 116, 104, 117, 98, 46, 99, 111, 109))
RAW_GITHUB_ALAN_ADI = metin_uret((114, 97, 119, 46, 103, 105, 116, 104, 117, 98, 117, 115, 101, 114, 99, 111, 110, 116, 101, 110, 116, 46, 99, 111, 109))
GITHUB_USERCONTENT_SONU = metin_uret((46, 103, 105, 116, 104, 117, 98, 117, 115, 101, 114, 99, 111, 110, 116, 101, 110, 116, 46, 99, 111, 109))
SURUM_INDIRME_YOLU = metin_uret((114, 101, 108, 101, 97, 115, 101, 115, 47, 100, 111, 119, 110, 108, 111, 97, 100))


def surum_parcala(surum):
    try:
        surum = str(surum).strip().lower()

        if surum.startswith("v"):
            surum = surum[1:]

        surum = surum.split("-", 1)[0]
        surum = surum.split("+", 1)[0]
        parcalar = surum.split(".")

        if len(parcalar) < 1 or len(parcalar) > 4:
            return None

        sayilar = []

        for parca in parcalar:
            if not parca.isdigit():
                return None
            sayilar.append(int(parca))

        while len(sayilar) < 3:
            sayilar.append(0)

        return tuple(sayilar)

    except Exception:
        return None


def manifest_yolunu_bul():
    global _manifest_yolu_onbellek, _manifest_yolu_arandi

    if _manifest_yolu_arandi:
        return _manifest_yolu_onbellek or ""

    _manifest_yolu_arandi = True

    try:
        dosya_yolu = os.path.abspath(__file__)
        global_plugins_klasoru = os.path.dirname(dosya_yolu)
        eklenti_kok_klasoru = os.path.dirname(global_plugins_klasoru)

        adaylar = [
            os.path.join(eklenti_kok_klasoru, "manifest.ini"),
            os.path.join(global_plugins_klasoru, "manifest.ini"),
        ]

        try:
            kod_eklentisi = addonHandler.getCodeAddon()

            if kod_eklentisi and getattr(kod_eklentisi, "path", None):
                adaylar.append(os.path.join(kod_eklentisi.path, "manifest.ini"))
        except Exception:
            pass

        klasor = global_plugins_klasoru

        for _sayac in range(5):
            adaylar.append(os.path.join(klasor, "manifest.ini"))
            ust_klasor = os.path.dirname(klasor)

            if ust_klasor == klasor:
                break

            klasor = ust_klasor

        gorulenler = set()

        for aday in adaylar:
            aday = os.path.abspath(aday)

            if aday in gorulenler:
                continue

            gorulenler.add(aday)

            if os.path.isfile(aday):
                _manifest_yolu_onbellek = aday
                gunluk_yaz("manifest bulundu: " + aday)
                return aday

        _manifest_yolu_onbellek = ""
        gunluk_yaz("manifest.ini bulunamadı.")
        return ""

    except Exception as hata:
        _manifest_yolu_onbellek = ""
        gunluk_yaz("manifest yolu aranırken hata: " + repr(hata))
        return ""


def tirnaklari_temizle(deger):
    deger = str(deger).strip()

    if len(deger) >= 2 and deger[0] == '"' and deger[-1] == '"':
        return deger[1:-1]

    return deger


def manifest_alani_oku(alan_adi):
    try:
        manifest_yolu = manifest_yolunu_bul()

        if not manifest_yolu:
            return ""

        aranan = str(alan_adi).strip().lower()

        with open(manifest_yolu, "r", encoding="utf-8-sig") as dosya:
            for satir in dosya:
                satir = satir.strip()

                if not satir or satir.startswith("#") or satir.startswith(";"):
                    continue

                if "=" not in satir:
                    continue

                anahtar, deger = satir.split("=", 1)

                if anahtar.strip().lower() == aranan:
                    return tirnaklari_temizle(deger)

        return ""

    except Exception as hata:
        gunluk_yaz("manifest alanı okunamadı: " + repr(hata))
        return ""


def mevcut_surumu_al():
    manifest_surumu = manifest_alani_oku("version")

    if surum_parcala(manifest_surumu):
        return manifest_surumu

    return ""


def eklenti_gorunen_adini_al():
    summary = manifest_alani_oku("summary").strip()

    if summary:
        return summary

    name = manifest_alani_oku("name").strip()

    if name:
        return name

    return "Güncelleme"


def github_depo_bilgisi_al():
    try:
        manifest_url = manifest_alani_oku("url").strip()
        parca = urllib.parse.urlparse(manifest_url)

        if parca.scheme.lower() != "https":
            return None

        if parca.netloc.lower() != GITHUB_ALAN_ADI:
            return None

        yol_parcalari = [bolum for bolum in parca.path.strip("/").split("/") if bolum]

        if len(yol_parcalari) != 2:
            return None

        kullanici_adi = yol_parcalari[0]
        depo_adi = yol_parcalari[1]

        if kullanici_adi.lower() != RESMI_GITHUB_KULLANICI_ADI_KUCUK:
            return None

        if not depo_adi:
            return None

        return {
            "kullanici": kullanici_adi,
            "kullanici_kucuk": kullanici_adi.lower(),
            "depo": depo_adi,
            "depo_kucuk": depo_adi.lower(),
        }

    except Exception as hata:
        gunluk_yaz("GitHub depo bilgisi alınamadı: " + repr(hata))
        return None


def guncelleme_linkini_al(depo_bilgisi):
    try:
        return (
            "https://"
            + RAW_GITHUB_ALAN_ADI
            + "/"
            + depo_bilgisi["kullanici"]
            + "/"
            + depo_bilgisi["depo"]
            + "/main/update.json"
        )
    except Exception:
        return ""


def indirme_yolu_on_ekini_al(depo_bilgisi):
    try:
        return (
            "/"
            + depo_bilgisi["kullanici_kucuk"]
            + "/"
            + depo_bilgisi["depo_kucuk"]
            + "/"
            + SURUM_INDIRME_YOLU
            + "/"
        )
    except Exception:
        return ""


def resmi_kanal_bilgilerini_al():
    try:
        manifest_author = manifest_alani_oku("author").strip().lower()
        resmi_ad_soyad = RESMI_AD_SOYAD.lower()
        resmi_eposta = RESMI_EPOSTA.lower()

        if resmi_ad_soyad not in manifest_author:
            return None

        if resmi_eposta not in manifest_author:
            return None

        depo_bilgisi = github_depo_bilgisi_al()

        if not depo_bilgisi:
            return None

        guncelleme_linki = guncelleme_linkini_al(depo_bilgisi)
        indirme_yolu_on_eki = indirme_yolu_on_ekini_al(depo_bilgisi)

        if not guncelleme_linki or not indirme_yolu_on_eki:
            return None

        depo_bilgisi["guncelleme_linki"] = guncelleme_linki
        depo_bilgisi["indirme_yolu_on_eki"] = indirme_yolu_on_eki
        return depo_bilgisi

    except Exception as hata:
        gunluk_yaz("resmî kanal bilgileri alınamadı: " + repr(hata))
        return None


EKLENTI_ADI = eklenti_gorunen_adini_al()


def sunucu_surum_daha_yeni_mi(sunucu_surum, mevcut_surum):
    sunucu = surum_parcala(sunucu_surum)
    mevcut = surum_parcala(mevcut_surum)

    if not sunucu or not mevcut:
        return False

    return sunucu > mevcut


def sha256_gecerli_mi(sha256_degeri):
    try:
        sha256_degeri = str(sha256_degeri).strip().lower()

        if len(sha256_degeri) != 64:
            return False

        int(sha256_degeri, 16)
        return True

    except Exception:
        return False


def github_yonlendirme_guvenli_mi(adres):
    try:
        parca = urllib.parse.urlparse(str(adres).strip())
        alan_adi = parca.netloc.lower()

        if parca.scheme != "https":
            return False

        if alan_adi == GITHUB_ALAN_ADI:
            return True

        if alan_adi.endswith(GITHUB_USERCONTENT_SONU):
            return True

        return False

    except Exception:
        return False


def guvenli_github_indirme_linki_mi(link, depo_bilgisi):
    try:
        parca = urllib.parse.urlparse(str(link).strip())
        alan_adi = parca.netloc.lower()
        yol = parca.path.lower()

        if parca.scheme != "https":
            return False

        if alan_adi != GITHUB_ALAN_ADI:
            return False

        if not yol.startswith(depo_bilgisi["indirme_yolu_on_eki"]):
            return False

        if not yol.endswith(".nvda-addon"):
            return False

        return True

    except Exception:
        return False


def json_oku(depo_bilgisi):
    try:
        istek = urllib.request.Request(
            depo_bilgisi["guncelleme_linki"],
            headers={"User-Agent": KULLANICI_ARACISI},
        )

        with urllib.request.urlopen(
            istek,
            timeout=BAGLANTI_ZAMAN_ASIMI,
            context=ssl_baglami_olustur(),
        ) as yanit:
            ham_veri = yanit.read(AZAMI_JSON_BOYUTU + 1)

        if len(ham_veri) > AZAMI_JSON_BOYUTU:
            return None

        veri = json.loads(ham_veri.decode("utf-8", errors="replace"))

        if not isinstance(veri, dict):
            return None

        return veri

    except Exception as hata:
        gunluk_yaz("update.json okunamadı: " + repr(hata))
        return None


def dosya_adi_guvenli_yap(metin):
    try:
        metin = str(metin).strip()
        karakterler = []

        for karakter in metin:
            if karakter.isalnum() or karakter in ("-", "_", "."):
                karakterler.append(karakter)
            else:
                karakterler.append("_")

        sonuc = "".join(karakterler).strip("._")
        return sonuc if sonuc else "guncelleme"

    except Exception:
        return "guncelleme"


def gecici_dosya_yolunu_al(yeni_surum, depo_bilgisi):
    surum_etiketi = dosya_adi_guvenli_yap(yeni_surum)
    depo_etiketi = dosya_adi_guvenli_yap(depo_bilgisi.get("depo", "eklenti"))
    gecici_klasor = os.path.join(
        tempfile.gettempdir(),
        "nvda_resmi_guncelleme_" + depo_etiketi,
    )
    os.makedirs(gecici_klasor, exist_ok=True)

    hedef_dosya = os.path.join(
        gecici_klasor,
        depo_etiketi + "-" + surum_etiketi + ".nvda-addon",
    )

    return hedef_dosya, hedef_dosya + ".tmp"


def eklenti_dosyasini_indir(indirme_linki, yeni_surum, beklenen_sha256, depo_bilgisi):
    gecici_dosya = None

    try:
        if not guvenli_github_indirme_linki_mi(indirme_linki, depo_bilgisi):
            return None

        if not sha256_gecerli_mi(beklenen_sha256):
            return None

        hedef_dosya, gecici_dosya = gecici_dosya_yolunu_al(yeni_surum, depo_bilgisi)

        istek = urllib.request.Request(
            indirme_linki,
            headers={"User-Agent": KULLANICI_ARACISI},
        )

        sha256 = hashlib.sha256()
        indirilen_boyut = 0

        with urllib.request.urlopen(
            istek,
            timeout=INDIRME_ZAMAN_ASIMI,
            context=ssl_baglami_olustur(),
        ) as yanit:
            son_adres = yanit.geturl()

            if son_adres and not github_yonlendirme_guvenli_mi(son_adres):
                return None

            icerik_uzunlugu = yanit.headers.get("Content-Length")

            if icerik_uzunlugu:
                try:
                    if int(icerik_uzunlugu) > AZAMI_EKLENTI_BOYUTU:
                        return None
                except Exception:
                    pass

            with open(gecici_dosya, "wb") as dosya:
                while True:
                    parca = yanit.read(64 * 1024)

                    if not parca:
                        break

                    indirilen_boyut += len(parca)

                    if indirilen_boyut > AZAMI_EKLENTI_BOYUTU:
                        return None

                    sha256.update(parca)
                    dosya.write(parca)

        if indirilen_boyut <= 0:
            return None

        hesaplanan_sha256 = sha256.hexdigest().lower()
        beklenen_sha256 = str(beklenen_sha256).strip().lower()

        if hesaplanan_sha256 != beklenen_sha256:
            return None

        os.replace(gecici_dosya, hedef_dosya)
        gecici_dosya = None
        return hedef_dosya

    except Exception as hata:
        gunluk_yaz("güncelleme dosyası indirilemedi: " + repr(hata))
        return None

    finally:
        if gecici_dosya and os.path.exists(gecici_dosya):
            try:
                os.remove(gecici_dosya)
            except Exception:
                pass


def kurulumu_baslat(dosya_yolu):
    try:
        if not dosya_yolu:
            return False

        if not os.path.isfile(dosya_yolu):
            return False

        if not dosya_yolu.lower().endswith(".nvda-addon"):
            return False

        os.startfile(dosya_yolu)
        return True

    except Exception:
        return False


def guncelleme_indirilemedi_mesaji():
    gui.messageBox(
        "Güncelleme dosyası indirilemedi. Lütfen internet bağlantınızı denetleyip daha sonra yeniden deneyiniz.",
        EKLENTI_ADI,
        wx.OK | wx.ICON_WARNING,
    )


def indirme_ve_kurulum_islemi(indirme_linki, yeni_surum, beklenen_sha256, depo_bilgisi):
    global _indirme_basladi

    with _durum_kilidi:
        if _indirme_basladi:
            return
        _indirme_basladi = True

    basarili = False

    try:
        dosya_yolu = eklenti_dosyasini_indir(
            indirme_linki,
            yeni_surum,
            beklenen_sha256,
            depo_bilgisi,
        )
        basarili = kurulumu_baslat(dosya_yolu)

        if basarili:
            wx.CallAfter(ui.message, "Güncelleme dosyası indirildi. Kurulum penceresi açılıyor.")
        else:
            wx.CallAfter(guncelleme_indirilemedi_mesaji)

    except Exception:
        wx.CallAfter(guncelleme_indirilemedi_mesaji)

    finally:
        if not basarili:
            with _durum_kilidi:
                _indirme_basladi = False


def guncelleme_penceresi_goster(yeni_surum, indirme_linki, aciklama, beklenen_sha256, depo_bilgisi):
    global _guncelleme_penceresi_acik

    with _durum_kilidi:
        if _guncelleme_penceresi_acik:
            return
        _guncelleme_penceresi_acik = True

    try:
        cevap = gui.messageBox(
            EKLENTI_ADI + "\n\n"
            "Yeni sürüm bulundu: " + str(yeni_surum) + "\n\n"
            "Yenilikler:\n"
            + str(aciklama).strip()
            + "\n\n"
            "Güncellemeyi indirip kurulumu başlatmak ister misiniz?",
            "Yeni Güncelleme Uyarısı",
            wx.YES_NO | wx.ICON_INFORMATION,
        )

        if cevap == wx.YES:
            threading.Thread(
                target=indirme_ve_kurulum_islemi,
                args=(indirme_linki, yeni_surum, beklenen_sha256, depo_bilgisi),
                daemon=True,
            ).start()

    except Exception:
        pass

    finally:
        with _durum_kilidi:
            _guncelleme_penceresi_acik = False


def guncelleme_kontrol_et():
    try:
        mevcut_surum = mevcut_surumu_al()

        if not surum_parcala(mevcut_surum):
            gunluk_yaz("kurulu sürüm geçerli okunamadı; denetim durduruldu.")
            return

        depo_bilgisi = resmi_kanal_bilgilerini_al()

        if not depo_bilgisi:
            gunluk_yaz("resmî kanal doğrulanmadı; denetim durduruldu.")
            return

        veri = json_oku(depo_bilgisi)

        if not veri:
            return

        sunucu_surum = veri.get("surum")
        indirme_linki = veri.get("link")
        aciklama = veri.get("aciklama") or "Yeni bir sürüm mevcut."
        beklenen_sha256 = veri.get("sha256")

        if not sunucu_surum:
            return

        if not guvenli_github_indirme_linki_mi(indirme_linki, depo_bilgisi):
            return

        if not sha256_gecerli_mi(beklenen_sha256):
            return

        if not sunucu_surum_daha_yeni_mi(sunucu_surum, mevcut_surum):
            return

        wx.CallAfter(
            guncelleme_penceresi_goster,
            sunucu_surum,
            indirme_linki,
            aciklama,
            beklenen_sha256,
            depo_bilgisi,
        )

    except Exception as hata:
        gunluk_yaz("beklenmeyen denetim hatası: " + repr(hata))


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self._guncelleme_zamanlayici = None
        self._kontrol_is_parcacigi = None

        try:
            self._guncelleme_zamanlayici = wx.CallLater(
                KONTROL_GECIKMESI_MS,
                self._guncelleme_kontrolunu_baslat,
            )
        except Exception:
            self._guncelleme_zamanlayici = None

    def terminate(self):
        try:
            if self._guncelleme_zamanlayici:
                self._guncelleme_zamanlayici.Stop()
                self._guncelleme_zamanlayici = None
        except Exception:
            pass

        self._kontrol_is_parcacigi = None
        super().terminate()

    def _guncelleme_kontrolunu_baslat(self):
        self._guncelleme_zamanlayici = None

        try:
            self._kontrol_is_parcacigi = threading.Thread(
                target=self._guncelleme_kontrol_is_parcacigi,
                daemon=True,
            )
            self._kontrol_is_parcacigi.start()
        except Exception:
            self._kontrol_is_parcacigi = None

    def _guncelleme_kontrol_is_parcacigi(self):
        try:
            guncelleme_kontrol_et()
        finally:
            self._kontrol_is_parcacigi = None
