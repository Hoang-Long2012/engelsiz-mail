# -*- coding: utf-8 -*-
# Engelsiz Mail Güncelleme Motoru
# Telif Hakkı (C) 2026 Mehmet Aykurt
#
# Bu dosya NVDA global plugin yapısına uygundur.
# Kullanıcıya teknik hata göstermez.
# Güncelleme varsa sorar, onay verilirse .nvda-addon dosyasını indirir
# ve Windows üzerinden NVDA eklenti kurulumunu başlatır.

import os
import json
import hashlib
import tempfile
import threading
import urllib.request
import urllib.parse

import wx
import gui
import globalPluginHandler


EKLENTI_ADI = "Engelsiz Mail"

MEVCUT_SURUM = "1.0.0"

GUNCELLEME_LINKI = "https://raw.githubusercontent.com/MehmetAykurt/engelsiz-mail/main/update.json"

KONTROL_GECIKMESI_MS = 7000

BAGLANTI_ZAMAN_ASIMI = 10

INDIRME_ZAMAN_ASIMI = 30

AZAMI_JSON_BOYUTU = 1024 * 1024

AZAMI_EKLENTI_BOYUTU = 150 * 1024 * 1024

KULLANICI_ARACISI = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "NVDA-Engelsiz-Mail-Update-Checker"
)

_guncelleme_penceresi_acik = False
_indirme_basladi = False


def surum_parcala(surum):
    """
    Sürüm numarasını karşılaştırılabilir sayısal parçaya dönüştürür.

    Kabul edilen örnekler:
    1.0
    1.0.0
    v1.0.0

    Karşılaştırma için 1.0 değeri 1.0.0 gibi kabul edilir.
    """
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


def sunucu_surum_daha_yeni_mi(sunucu_surum, mevcut_surum):
    """
    Sunucudaki sürüm mevcut sürümden büyükse True döndürür.
    Hatalı sürüm biçiminde kullanıcıya hata göstermez ve False döndürür.
    """
    try:
        sunucu = surum_parcala(sunucu_surum)
        mevcut = surum_parcala(mevcut_surum)

        if not sunucu or not mevcut:
            return False

        return sunucu > mevcut

    except Exception:
        return False


def guvenli_http_linki_mi(link):
    """
    Sadece http ve https bağlantılarına izin verir.
    """
    try:
        parca = urllib.parse.urlparse(str(link).strip())
        return parca.scheme in ("http", "https") and bool(parca.netloc)

    except Exception:
        return False


def json_oku():
    """
    GitHub üzerindeki update.json dosyasını okur.
    Hata olursa kullanıcıya hiçbir uyarı göstermez.
    """
    try:
        req = urllib.request.Request(
            GUNCELLEME_LINKI,
            headers={"User-Agent": KULLANICI_ARACISI}
        )

        with urllib.request.urlopen(req, timeout=BAGLANTI_ZAMAN_ASIMI) as response:
            ham_veri = response.read(AZAMI_JSON_BOYUTU + 1)

        if len(ham_veri) > AZAMI_JSON_BOYUTU:
            return None

        return json.loads(ham_veri.decode("utf-8"))

    except Exception:
        return None


def dosya_adi_guvenli_yap(metin):
    """
    Dosya adında sorun çıkarabilecek karakterleri temizler.
    """
    try:
        metin = str(metin).strip()
        izinli = []

        for karakter in metin:
            if karakter.isalnum() or karakter in ("-", "_", "."):
                izinli.append(karakter)
            else:
                izinli.append("_")

        sonuc = "".join(izinli).strip("._")

        if not sonuc:
            sonuc = "guncelleme"

        return sonuc

    except Exception:
        return "guncelleme"


def eklenti_dosyasini_indir(indirme_linki, yeni_surum, beklenen_sha256=None):
    """
    .nvda-addon dosyasını geçici klasöre indirir.
    İsteğe bağlı olarak SHA256 doğrulaması yapar.

    Hata olursa kullanıcıya hiçbir uyarı göstermez.
    """
    try:
        if not guvenli_http_linki_mi(indirme_linki):
            return None

        surum_etiketi = dosya_adi_guvenli_yap(yeni_surum)

        gecici_klasor = os.path.join(
            tempfile.gettempdir(),
            "mehmet_aykurt_engelsiz_mail_guncelleme"
        )

        os.makedirs(gecici_klasor, exist_ok=True)

        hedef_dosya = os.path.join(
            gecici_klasor,
            f"Engelsiz-Mail-{surum_etiketi}.nvda-addon"
        )

        gecici_dosya = hedef_dosya + ".tmp"

        req = urllib.request.Request(
            indirme_linki,
            headers={"User-Agent": KULLANICI_ARACISI}
        )

        sha256 = hashlib.sha256()
        indirilen_boyut = 0

        with urllib.request.urlopen(req, timeout=INDIRME_ZAMAN_ASIMI) as response:
            icerik_uzunlugu = response.headers.get("Content-Length")

            if icerik_uzunlugu:
                try:
                    if int(icerik_uzunlugu) > AZAMI_EKLENTI_BOYUTU:
                        return None
                except Exception:
                    pass

            with open(gecici_dosya, "wb") as dosya:
                while True:
                    parca = response.read(64 * 1024)

                    if not parca:
                        break

                    indirilen_boyut += len(parca)

                    if indirilen_boyut > AZAMI_EKLENTI_BOYUTU:
                        try:
                            dosya.close()
                        except Exception:
                            pass

                        try:
                            os.remove(gecici_dosya)
                        except Exception:
                            pass

                        return None

                    sha256.update(parca)
                    dosya.write(parca)

        if indirilen_boyut <= 0:
            try:
                os.remove(gecici_dosya)
            except Exception:
                pass

            return None

        if beklenen_sha256:
            beklenen_sha256 = str(beklenen_sha256).strip().lower()
            hesaplanan_sha256 = sha256.hexdigest().lower()

            if beklenen_sha256 != hesaplanan_sha256:
                try:
                    os.remove(gecici_dosya)
                except Exception:
                    pass

                return None

        os.replace(gecici_dosya, hedef_dosya)

        return hedef_dosya

    except Exception:
        try:
            if "gecici_dosya" in locals() and os.path.exists(gecici_dosya):
                os.remove(gecici_dosya)
        except Exception:
            pass

        return None


def kurulumu_baslat(dosya_yolu):
    """
    İndirilen .nvda-addon dosyasını Windows üzerinden açar.
    Bu işlem normalde NVDA eklenti kurulum penceresini başlatır.
    Hata olursa kullanıcıya teknik uyarı göstermez.
    """
    try:
        if not dosya_yolu:
            return

        if not os.path.isfile(dosya_yolu):
            return

        os.startfile(dosya_yolu)

    except Exception:
        pass


def indirme_ve_kurulum_islemi(indirme_linki, yeni_surum, beklenen_sha256=None):
    """
    Güncellemeyi indirir ve kurulum işlemini başlatır.
    """
    global _indirme_basladi

    try:
        if _indirme_basladi:
            return

        _indirme_basladi = True

        dosya_yolu = eklenti_dosyasini_indir(
            indirme_linki,
            yeni_surum,
            beklenen_sha256
        )

        if dosya_yolu:
            kurulumu_baslat(dosya_yolu)

    except Exception:
        pass


def guncelleme_penceresi_goster(yeni_surum, indirme_linki, aciklama, beklenen_sha256=None):
    """
    Kullanıcıya yalnızca güncelleme bulunduğunda soru sorar.
    Teknik hata göstermez.
    """
    global _guncelleme_penceresi_acik

    try:
        if _guncelleme_penceresi_acik:
            return

        _guncelleme_penceresi_acik = True

        cevap = gui.messageBox(
            f"{EKLENTI_ADI}\n\n"
            f"Yeni sürüm bulundu: {yeni_surum}\n\n"
            f"Yenilikler:\n"
            f"{aciklama}\n\n"
            f"Güncellemeyi indirip kurulumu başlatmak ister misiniz?",
            "Yeni Güncelleme Uyarısı",
            wx.YES_NO | wx.ICON_INFORMATION
        )

        if cevap == wx.YES:
            threading.Thread(
                target=indirme_ve_kurulum_islemi,
                args=(indirme_linki, yeni_surum, beklenen_sha256),
                daemon=True
            ).start()

    except Exception:
        pass

    finally:
        _guncelleme_penceresi_acik = False


def guncelleme_kontrol_et():
    """
    Güncelleme kontrolünü arka planda yapar.
    Kullanıcıya yalnızca gerçekten yeni sürüm varsa soru gösterir.
    """
    try:
        veri = json_oku()

        if not isinstance(veri, dict):
            return

        sunucu_surum = veri.get("surum")
        indirme_linki = veri.get("link")
        aciklama = veri.get(
            "aciklama",
            "Yeni bir sürüm mevcut."
        )
        beklenen_sha256 = veri.get("sha256")

        if not sunucu_surum:
            return

        if not indirme_linki:
            return

        if not guvenli_http_linki_mi(indirme_linki):
            return

        if sunucu_surum_daha_yeni_mi(sunucu_surum, MEVCUT_SURUM):
            wx.CallAfter(
                guncelleme_penceresi_goster,
                sunucu_surum,
                indirme_linki,
                aciklama,
                beklenen_sha256
            )

    except Exception:
        pass


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    def __init__(self):
        super(GlobalPlugin, self).__init__()

        try:
            self._guncellemeZamanlayici = wx.CallLater(
                KONTROL_GECIKMESI_MS,
                self._guncelleme_kontrolunu_baslat
            )

        except Exception:
            pass

    def _guncelleme_kontrolunu_baslat(self):
        try:
            threading.Thread(
                target=guncelleme_kontrol_et,
                daemon=True
            ).start()

        except Exception:
            pass
