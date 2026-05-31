# -*- coding: utf-8 -*-
# Engelsiz Mail
# Telif Hakkı (C) 2026 Mehmet Aykurt

import base64
import ctypes
from ctypes import wintypes
import email
import email.utils
from email import policy as email_policy
from email.header import decode_header
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import parsedate_to_datetime
import globalPluginHandler
import globalVars
import gui
import html
import json
from logHandler import log
import mimetypes
import os
import re
import socket
import ssl
import tempfile
import threading
import wx
import ui


EKLENTI_ADI = "Engelsiz Mail"
AYARLAR_DOSYASI = os.path.join(globalVars.appArgs.configPath, "engelsizmail_ayarlar.json")
REHBER_DOSYASI = os.path.join(globalVars.appArgs.configPath, "engelsizmail_rehber.json")

GMAIL_IMAP_SUNUCU = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
GMAIL_SMTP_SUNUCU = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465
BAGLANTI_ZAMAN_ASIMI = 20
VARSAYILAN_MESAJ_SAYISI = 25
EN_AZ_MESAJ_SAYISI = 1
EN_COK_MESAJ_SAYISI = 100
YENI_ARSIV_SECENEGI = "-- Yeni Bir Arşiv Klasörü Oluştur --"
HESAP_BILGISI_EKSIK_UYARISI = (
    "Lütfen önce Google Hesabına Bağlan seçeneğine girerek "
    "hesap bilgilerinizi kaydedin."
)
MENU_BILDIRIM_GECIKMESI_MS = 450
SIFRE_DPAPI_ALANI = "sifre_dpapi"
SIFRE_DUZ_METIN_ALANI = "sifre"
SIFRE_DPAPI_ON_EK = "dpapi-v1:"
MESAJ_SAYISI_ALANI = "mesaj_sayisi"
ONERI_GORUS_ALICI = "m.aykurt38@gmail.com"

SISTEM_KLASORLERI = [
    "Gelen Kutusu",
    "Tüm Postalar",
    "Gönderilmiş Öğeler",
    "Taslaklar",
    "Çöp Kutusu",
    "Spam",
]

VARSAYILAN_KLASOR_HARITASI = {
    "Gelen Kutusu": "INBOX",
    "Tüm Postalar": '"[Gmail]/All Mail"',
    "Gönderilmiş Öğeler": '"[Gmail]/Sent Mail"',
    "Taslaklar": '"[Gmail]/Drafts"',
    "Çöp Kutusu": '"[Gmail]/Trash"',
    "Spam": '"[Gmail]/Spam"',
}


class MailHatasi(Exception):
    """Kullanıcıya sade biçimde bildirilebilecek posta işlemi hatası."""


class YerelImapIstemcisi:
    """NVDA ortamında imaplib bulunmadığında kullanılan sınırlı IMAP istemcisi."""

    def __init__(self, sunucu, port, timeout=BAGLANTI_ZAMAN_ASIMI):
        self.sunucu = sunucu
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.dosya = None
        self._etiket_sayaci = 0
        self._baglan()

    def _baglan(self):
        ctx = ssl.create_default_context()
        ham_soket = socket.create_connection((self.sunucu, self.port), timeout=self.timeout)
        self.sock = ctx.wrap_socket(ham_soket, server_hostname=self.sunucu)
        self.dosya = self.sock.makefile("rb")
        karsilama = self.dosya.readline()
        if not karsilama:
            raise MailHatasi("IMAP sunucusundan yanıt alınamadı.")

    def _yeni_etiket(self):
        self._etiket_sayaci += 1
        return f"A{self._etiket_sayaci:04d}"

    def _tirnakla(self, metin):
        metin = str(metin).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{metin}"'

    def _yanit_oku(self, etiket):
        etiket_bytes = etiket.encode("ascii", errors="ignore")
        veriler = []
        son_satir = b""

        while True:
            satir = self.dosya.readline()
            if not satir:
                raise MailHatasi("IMAP bağlantısı beklenmedik biçimde kapandı.")

            eslesme = re.search(br"\{(\d+)\}\r?\n$", satir)
            if eslesme:
                uzunluk = int(eslesme.group(1))
                ham = self.dosya.read(uzunluk)
                veriler.append((satir.rstrip(b"\r\n"), ham))
                continue

            temiz_satir = satir.rstrip(b"\r\n")
            veriler.append(temiz_satir)
            if temiz_satir.startswith(etiket_bytes + b" ") or temiz_satir == etiket_bytes:
                son_satir = temiz_satir
                break

        parcalar = son_satir.decode("utf-8", errors="replace").split()
        durum = parcalar[1].upper() if len(parcalar) > 1 else "NO"
        return durum, veriler

    def _komut(self, komut):
        etiket = self._yeni_etiket()
        self.sock.sendall(f"{etiket} {komut}\r\n".encode("utf-8"))
        return self._yanit_oku(etiket)

    def login(self, eposta, sifre):
        return self._komut(f"LOGIN {self._tirnakla(eposta)} {self._tirnakla(sifre)}")

    def logout(self):
        try:
            return self._komut("LOGOUT")
        finally:
            try:
                if self.dosya:
                    self.dosya.close()
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass

    def list(self):
        return self._komut('LIST "" "*"')

    def select(self, klasor, readonly=False):
        komut = "EXAMINE" if readonly else "SELECT"
        return self._komut(f"{komut} {klasor}")

    def uid(self, *args):
        temiz_argumanlar = [str(arg) for arg in args if arg is not None]
        return self._komut("UID " + " ".join(temiz_argumanlar))

    def delete(self, klasor):
        return self._komut(f"DELETE {klasor}")

    def create(self, klasor):
        return self._komut(f"CREATE {klasor}")

    def expunge(self):
        return self._komut("EXPUNGE")

    def close(self):
        return self._komut("CLOSE")

    def append(self, klasor, bayraklar, tarih, mesaj_verisi):
        """IMAP APPEND komutuyla klasöre ham ileti ekler."""
        if isinstance(mesaj_verisi, str):
            mesaj_verisi = mesaj_verisi.encode("utf-8")
        mesaj_verisi = mesaj_verisi or b""

        etiket = self._yeni_etiket()
        bayrak_parcasi = f" {bayraklar}" if bayraklar else ""
        tarih_parcasi = f" {self._tirnakla(tarih)}" if tarih else ""
        komut = f"{etiket} APPEND {klasor}{bayrak_parcasi}{tarih_parcasi} {{{len(mesaj_verisi)}}}\r\n"
        self.sock.sendall(komut.encode("utf-8"))

        satir = self.dosya.readline()
        if not satir:
            raise MailHatasi("IMAP sunucusundan taslak kaydetme yanıtı alınamadı.")

        temiz_satir = satir.rstrip(b"\r\n")
        if temiz_satir.startswith(b"+"):
            self.sock.sendall(mesaj_verisi + b"\r\n")
            return self._yanit_oku(etiket)

        # Bazı hata durumlarında sunucu devam yanıtı yerine doğrudan son yanıt döndürebilir.
        etiket_bytes = etiket.encode("ascii", errors="ignore")
        veriler = [temiz_satir]
        if temiz_satir.startswith(etiket_bytes + b" ") or temiz_satir == etiket_bytes:
            parcalar = temiz_satir.decode("utf-8", errors="replace").split()
            durum = parcalar[1].upper() if len(parcalar) > 1 else "NO"
            return durum, veriler

        durum, devam = self._yanit_oku(etiket)
        return durum, veriler + devam


class ImapBaglantisi:
    """IMAP bağlantısını güvenli biçimde açıp kapatan yardımcı sınıf."""

    def __init__(self, ayarlar):
        self.ayarlar = ayarlar
        self.imap = None

    def __enter__(self):
        eposta = self.ayarlar.get("eposta", "")
        sifre = self.ayarlar.get("sifre", "")
        if not eposta or not sifre:
            raise MailHatasi("Hesap bilgileri eksik.")
        self.imap = YerelImapIstemcisi(GMAIL_IMAP_SUNUCU, GMAIL_IMAP_PORT, BAGLANTI_ZAMAN_ASIMI)
        tip, _veri = self.imap.login(eposta, sifre)
        if tip != "OK":
            raise MailHatasi("Gmail hesabına giriş yapılamadı.")
        return self.imap

    def __exit__(self, exc_type, exc, tb):
        if not self.imap:
            return
        try:
            self.imap.logout()
        except Exception:
            pass


def hata_kaydet(baslik, hata=None):
    """Teknik ayrıntıları NVDA günlüğüne yazar; kullanıcıya ham hata göstermez."""
    try:
        if hata:
            log.exception(f"{EKLENTI_ADI}: {baslik}")
        else:
            log.debug(f"{EKLENTI_ADI}: {baslik}")
    except Exception:
        pass


def pencere_kullanilabilir_mi(pencere):
    """Kapanmış veya yok edilmekte olan wx pencerelerine geri dönüşü engeller."""
    try:
        if pencere is None:
            return False
        if getattr(pencere, "_kapatildi", False):
            return False
        if hasattr(pencere, "IsBeingDeleted") and pencere.IsBeingDeleted():
            return False
        return True
    except Exception:
        return False


def guvenli_call_after(pencere, islev, *args, **kwargs):
    """Arka plan işlemlerinden arayüze güvenli dönüş yapar."""
    def calistir():
        if not pencere_kullanilabilir_mi(pencere):
            return
        try:
            islev(*args, **kwargs)
        except Exception as e:
            hata_kaydet("Arayüz güncellemesi yapılamadı.", e)

    wx.CallAfter(calistir)


def bildirim_soyle(mesaj, gecikme_ms=0):
    """NVDA konuşması menü kapanışında kesilmesin diye gerekirse bildirimi geciktirir."""
    try:
        if gecikme_ms and gecikme_ms > 0:
            wx.CallLater(gecikme_ms, ui.message, mesaj)
        else:
            ui.message(mesaj)
    except Exception as e:
        hata_kaydet("Bildirim verilemedi.", e)


def arka_planda_calistir(hedef, *args):
    thread = threading.Thread(target=hedef, args=args, daemon=True)
    thread.start()
    return thread


def guvenli_json_oku(dosya_yolu, varsayilan):
    try:
        if not os.path.exists(dosya_yolu):
            return varsayilan
        with open(dosya_yolu, "r", encoding="utf-8") as dosya:
            veri = json.load(dosya)
        return veri if isinstance(veri, type(varsayilan)) else varsayilan
    except Exception as e:
        hata_kaydet(f"JSON dosyası okunamadı: {dosya_yolu}", e)
        return varsayilan


def guvenli_json_yaz(dosya_yolu, veri):
    klasor = os.path.dirname(dosya_yolu)
    os.makedirs(klasor, exist_ok=True)
    fd, gecici_yol = tempfile.mkstemp(prefix="engelsizmail_", suffix=".tmp", dir=klasor)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as dosya:
            json.dump(veri, dosya, ensure_ascii=False, indent=2)
        os.replace(gecici_yol, dosya_yolu)
        return True
    except Exception as e:
        hata_kaydet(f"JSON dosyası yazılamadı: {dosya_yolu}", e)
        try:
            os.remove(gecici_yol)
        except Exception:
            pass
        return False


def mesaj_sayisini_duzenle(deger, varsayilan=VARSAYILAN_MESAJ_SAYISI):
    """Ayar dosyasından gelen mesaj sayısını güvenli aralığa çeker."""
    try:
        sayi = int(str(deger).strip())
    except Exception:
        sayi = int(varsayilan)
    if sayi < EN_AZ_MESAJ_SAYISI:
        return EN_AZ_MESAJ_SAYISI
    if sayi > EN_COK_MESAJ_SAYISI:
        return EN_COK_MESAJ_SAYISI
    return sayi


def mesaj_sayisi_metnini_dogrula(metin):
    """Ayar penceresindeki mesaj sayısı alanını doğrular."""
    metin = str(metin or "").strip()
    if not metin:
        raise MailHatasi("Listelenecek mesaj sayısı boş bırakılamaz.")
    try:
        sayi = int(metin)
    except Exception as e:
        raise MailHatasi("Listelenecek mesaj sayısı yalnızca rakamlardan oluşmalıdır.") from e
    if sayi < EN_AZ_MESAJ_SAYISI or sayi > EN_COK_MESAJ_SAYISI:
        raise MailHatasi(f"Listelenecek mesaj sayısı {EN_AZ_MESAJ_SAYISI} ile {EN_COK_MESAJ_SAYISI} arasında olmalıdır.")
    return sayi


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.c_void_p),
    ]


def _dpapi_modullerini_al():
    """Windows DPAPI işlevlerini döndürür."""
    if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
        raise MailHatasi("Windows DPAPI bu ortamda kullanılamıyor.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _blob_olustur(veri):
    tampon = ctypes.create_string_buffer(veri)
    blob = _DATA_BLOB(len(veri), ctypes.cast(tampon, ctypes.c_void_p))
    return blob, tampon


def _windows_hatasi(mesaj):
    hata_kodu = ctypes.get_last_error()
    if hata_kodu:
        return f"{mesaj} Windows hata kodu: {hata_kodu}."
    return mesaj


def uygulama_sifresini_sifrele(sifre):
    """Google uygulama şifresini Windows kullanıcı hesabına bağlı biçimde şifreler."""
    sifre = str(sifre or "").strip().replace(" ", "")
    if not sifre:
        return ""

    crypt32, kernel32 = _dpapi_modullerini_al()
    veri = sifre.encode("utf-8")
    giris_blob, _tampon = _blob_olustur(veri)
    cikis_blob = _DATA_BLOB()

    sonuc = crypt32.CryptProtectData(
        ctypes.byref(giris_blob),
        EKLENTI_ADI,
        None,
        None,
        None,
        0,
        ctypes.byref(cikis_blob),
    )
    if not sonuc:
        raise MailHatasi(_windows_hatasi("Uygulama şifresi şifrelenemedi."))

    try:
        sifreli_veri = ctypes.string_at(cikis_blob.pbData, cikis_blob.cbData)
    finally:
        if cikis_blob.pbData:
            kernel32.LocalFree(cikis_blob.pbData)

    return SIFRE_DPAPI_ON_EK + base64.b64encode(sifreli_veri).decode("ascii")


def uygulama_sifresini_coz(sifreli_deger):
    """Windows DPAPI ile saklanan Google uygulama şifresini çözer."""
    sifreli_deger = str(sifreli_deger or "").strip()
    if not sifreli_deger:
        return ""
    if not sifreli_deger.startswith(SIFRE_DPAPI_ON_EK):
        raise MailHatasi("Uygulama şifresi desteklenmeyen bir biçimde saklanmış.")

    try:
        sifreli_veri = base64.b64decode(sifreli_deger[len(SIFRE_DPAPI_ON_EK):].encode("ascii"), validate=True)
    except Exception as e:
        raise MailHatasi("Kayıtlı uygulama şifresi okunamadı.") from e

    crypt32, kernel32 = _dpapi_modullerini_al()
    giris_blob, _tampon = _blob_olustur(sifreli_veri)
    cikis_blob = _DATA_BLOB()

    sonuc = crypt32.CryptUnprotectData(
        ctypes.byref(giris_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(cikis_blob),
    )
    if not sonuc:
        raise MailHatasi(_windows_hatasi("Kayıtlı uygulama şifresi çözülemedi."))

    try:
        duz_veri = ctypes.string_at(cikis_blob.pbData, cikis_blob.cbData)
    finally:
        if cikis_blob.pbData:
            kernel32.LocalFree(cikis_blob.pbData)

    return duz_veri.decode("utf-8", errors="replace").strip().replace(" ", "")


def _duz_metin_sifreyi_sifreliye_tasi(ayarlar, eposta, sifre):
    """Eski ayar dosyasındaki düz metin şifreyi DPAPI alanına taşır."""
    if not sifre:
        return
    try:
        yeni_ayarlar = dict(ayarlar) if isinstance(ayarlar, dict) else {}
        yeni_ayarlar["eposta"] = eposta
        yeni_ayarlar[SIFRE_DPAPI_ALANI] = uygulama_sifresini_sifrele(sifre)
        yeni_ayarlar.pop(SIFRE_DUZ_METIN_ALANI, None)
        guvenli_json_yaz(AYARLAR_DOSYASI, yeni_ayarlar)
    except Exception as e:
        hata_kaydet("Düz metin uygulama şifresi şifreli alana taşınamadı.", e)


def ayarlari_yukle():
    ayarlar = guvenli_json_oku(AYARLAR_DOSYASI, {})
    if not isinstance(ayarlar, dict):
        ayarlar = {}

    eposta = str(ayarlar.get("eposta", "")).strip()
    sifre = ""

    sifreli_deger = str(ayarlar.get(SIFRE_DPAPI_ALANI, "")).strip()
    if sifreli_deger:
        try:
            sifre = uygulama_sifresini_coz(sifreli_deger)
        except Exception as e:
            hata_kaydet("Kayıtlı uygulama şifresi çözülemedi.", e)
            sifre = ""
    else:
        sifre = str(ayarlar.get(SIFRE_DUZ_METIN_ALANI, "")).strip().replace(" ", "")
        if sifre:
            _duz_metin_sifreyi_sifreliye_tasi(ayarlar, eposta, sifre)

    mesaj_sayisi = mesaj_sayisini_duzenle(ayarlar.get(MESAJ_SAYISI_ALANI, VARSAYILAN_MESAJ_SAYISI))

    return {
        "eposta": eposta,
        "sifre": sifre,
        MESAJ_SAYISI_ALANI: mesaj_sayisi,
    }


def ayarlari_kaydet(eposta, sifre, mesaj_sayisi=None):
    eposta = str(eposta or "").strip()
    sifre = str(sifre or "").strip().replace(" ", "")
    try:
        sifreli_deger = uygulama_sifresini_sifrele(sifre)
    except Exception as e:
        hata_kaydet("Uygulama şifresi şifrelenemedi.", e)
        return False

    mevcut_ayarlar = guvenli_json_oku(AYARLAR_DOSYASI, {})
    if not isinstance(mevcut_ayarlar, dict):
        mevcut_ayarlar = {}

    if mesaj_sayisi is None:
        mesaj_sayisi = mesaj_sayisini_duzenle(mevcut_ayarlar.get(MESAJ_SAYISI_ALANI, VARSAYILAN_MESAJ_SAYISI))
    else:
        mesaj_sayisi = mesaj_sayisini_duzenle(mesaj_sayisi)

    yeni_ayarlar = dict(mevcut_ayarlar)
    yeni_ayarlar["eposta"] = eposta
    yeni_ayarlar[SIFRE_DPAPI_ALANI] = sifreli_deger
    yeni_ayarlar[MESAJ_SAYISI_ALANI] = mesaj_sayisi
    yeni_ayarlar.pop(SIFRE_DUZ_METIN_ALANI, None)
    return guvenli_json_yaz(AYARLAR_DOSYASI, yeni_ayarlar)


def mesaj_sayisini_kaydet(mesaj_sayisi):
    """Listelenecek e-posta sayısını hesap bilgilerine dokunmadan kaydeder."""
    mevcut_ayarlar = guvenli_json_oku(AYARLAR_DOSYASI, {})
    if not isinstance(mevcut_ayarlar, dict):
        mevcut_ayarlar = {}
    yeni_ayarlar = dict(mevcut_ayarlar)
    yeni_ayarlar[MESAJ_SAYISI_ALANI] = mesaj_sayisini_duzenle(mesaj_sayisi)
    yeni_ayarlar.pop(SIFRE_DUZ_METIN_ALANI, None)
    return guvenli_json_yaz(AYARLAR_DOSYASI, yeni_ayarlar)


def rehberi_yukle():
    adresler = guvenli_json_oku(REHBER_DOSYASI, [])
    if not isinstance(adresler, list):
        return []
    temiz = []
    for adres in adresler:
        adres = str(adres).strip()
        if adres and adres not in temiz:
            temiz.append(adres)
    return temiz[:200]


def rehbere_ekle(yeni_adres):
    yeni_adres = str(yeni_adres or "").strip()
    if not yeni_adres:
        return
    adresler = rehberi_yukle()
    if yeni_adres in adresler:
        adresler.remove(yeni_adres)
    adresler.insert(0, yeni_adres)
    guvenli_json_yaz(REHBER_DOSYASI, adresler[:200])


def guvenli_coz(metin):
    if not metin:
        return ""
    try:
        sonuc = []
        for icerik, karakter_kumesi in decode_header(str(metin)):
            if isinstance(icerik, bytes):
                sonuc.append(icerik.decode(karakter_kumesi or "utf-8", errors="replace"))
            else:
                sonuc.append(str(icerik))
        return "".join(sonuc).strip()
    except Exception:
        return str(metin).strip()


def turkce_tarih_yap(tarih_metni):
    if not tarih_metni:
        return "Tarih yok"
    aylar = {
        1: "Ocak",
        2: "Şubat",
        3: "Mart",
        4: "Nisan",
        5: "Mayıs",
        6: "Haziran",
        7: "Temmuz",
        8: "Ağustos",
        9: "Eylül",
        10: "Ekim",
        11: "Kasım",
        12: "Aralık",
    }
    try:
        tarih = parsedate_to_datetime(tarih_metni)
        return f"{tarih.day} {aylar[tarih.month]} {tarih.year} {tarih.hour:02d}:{tarih.minute:02d}"
    except Exception:
        return str(tarih_metni)


def html_temizle(html_metni):
    if not html_metni:
        return ""
    metin = re.sub(
        r"<(style|script|head)[^>]*>.*?</\1>",
        "",
        html_metni,
        flags=re.IGNORECASE | re.DOTALL,
    )
    metin = re.sub(r"</?(br|p|div|tr|li|h[1-6])[^>]*>", "\n", metin, flags=re.IGNORECASE)
    metin = re.sub(r"<[^>]+>", " ", metin)
    metin = html.unescape(metin)
    metin = re.sub(r"[ \t]+", " ", metin)
    satirlar = [satir.strip() for satir in metin.splitlines()]
    return "\n".join(satir for satir in satirlar if satir).strip()


def encode_mutf7(metin):
    if not metin:
        return ""
    sonuc = []
    ascii_olmayan = []

    def bosalt():
        if ascii_olmayan:
            veri = "".join(ascii_olmayan).encode("utf-16-be")
            kod = base64.b64encode(veri).decode("ascii").replace("/", ",").rstrip("=")
            sonuc.append("&" + kod + "-")
            ascii_olmayan.clear()

    for karakter in metin:
        if karakter == "&":
            bosalt()
            sonuc.append("&-")
        elif 0x20 <= ord(karakter) <= 0x7E:
            bosalt()
            sonuc.append(karakter)
        else:
            ascii_olmayan.append(karakter)
    bosalt()
    return "".join(sonuc)


def decode_mutf7(metin):
    if not metin or "&" not in metin:
        return metin
    sonuc = []
    parcalar = metin.split("&")
    sonuc.append(parcalar[0])
    for parca in parcalar[1:]:
        if "-" in parca:
            kod, kalan = parca.split("-", 1)
            if not kod:
                sonuc.append("&" + kalan)
            else:
                b64 = kod.replace(",", "/")
                b64 += "=" * ((4 - len(b64) % 4) % 4)
                try:
                    sonuc.append(base64.b64decode(b64).decode("utf-16-be") + kalan)
                except Exception:
                    sonuc.append("&" + parca)
        else:
            sonuc.append("&" + parca)
    return "".join(sonuc)


def imap_tirnakli_ham_ad(raw_ad):
    """LIST komutundan gelen ham IMAP klasör adını yeniden kodlamadan güvenle tırnaklar."""
    raw_ad = str(raw_ad or "").strip()
    if raw_ad.upper() == "INBOX":
        return "INBOX"
    if raw_ad.startswith('"') and raw_ad.endswith('"'):
        return raw_ad
    raw_ad = raw_ad.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{raw_ad}"'


def imap_klasor_adi_hazirla(klasor_adi):
    """Kullanıcının yazdığı görünen klasör adını IMAP klasör adına dönüştürür."""
    klasor_adi = str(klasor_adi or "").strip()
    if klasor_adi.upper() == "INBOX":
        return "INBOX"
    if klasor_adi.startswith('"') and klasor_adi.endswith('"'):
        return klasor_adi
    kodlu = encode_mutf7(klasor_adi)
    kodlu = kodlu.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{kodlu}"'


def imap_liste_satiri_ayristir(satir):
    try:
        if isinstance(satir, bytes):
            satir = satir.decode("utf-8", errors="replace")
        satir = satir.strip()
        eslesme = re.match(r'^(?:\* LIST )?\((?P<flags>.*?)\) (?P<delim>NIL|".*?") (?P<name>.+)$', satir)
        if not eslesme:
            return None
        bayraklar = eslesme.group("flags").upper()
        ad = eslesme.group("name").strip()
        if ad.startswith('"') and ad.endswith('"'):
            ad = ad[1:-1]
            ad = ad.replace('\\"', '"').replace('\\\\', '\\')
        return bayraklar, ad, decode_mutf7(ad)
    except Exception as e:
        hata_kaydet("IMAP klasör satırı ayrıştırılamadı.", e)
        return None


def uidleri_ayristir(search_sonucu):
    uidler = []
    try:
        for parca in search_sonucu or []:
            if isinstance(parca, tuple):
                continue
            if isinstance(parca, bytes):
                metin = parca.decode("ascii", errors="ignore")
            else:
                metin = str(parca)
            metin = metin.strip()
            if not metin:
                continue
            bolumler = metin.split()
            if len(bolumler) >= 2 and bolumler[0] == "*" and bolumler[1].upper() == "SEARCH":
                adaylar = bolumler[2:]
            else:
                adaylar = bolumler
            for aday in adaylar:
                if aday.isdigit() and aday not in uidler:
                    uidler.append(aday)
    except Exception as e:
        hata_kaydet("UID listesi ayrıştırılamadı.", e)
    return uidler


def guvenli_dosya_adi(metin, varsayilan="dosya", azami_uzunluk=90):
    metin = guvenli_coz(metin or varsayilan)
    metin = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", metin)
    metin = re.sub(r"\s+", " ", metin).strip(" ._")
    if not metin:
        metin = varsayilan
    return metin[:azami_uzunluk].strip(" ._") or varsayilan


def benzersiz_yol(klasor, dosya_adi):
    ad, uzanti = os.path.splitext(dosya_adi)
    aday = os.path.join(klasor, dosya_adi)
    sayac = 1
    while os.path.exists(aday):
        aday = os.path.join(klasor, f"{ad}_{sayac}{uzanti}")
        sayac += 1
    return aday


def alici_listesi_yap(kime):
    adresler = []
    for _ad, adres in email.utils.getaddresses([kime.replace(";", ",")]):
        adres = adres.strip()
        if adres and "@" in adres and adres not in adresler:
            adresler.append(adres)
    return adresler


def adres_basligini_duzenle(deger):
    """Taslaklardaki alıcı başlıklarını tek satırlık düzenlenebilir metne çevirir."""
    adresler = []
    for ad, adres in email.utils.getaddresses([str(deger or "")]):
        adres = adres.strip()
        ad = guvenli_coz(ad).strip()
        if not adres:
            continue
        if ad:
            bicimli = email.utils.formataddr((ad, adres))
        else:
            bicimli = adres
        if bicimli not in adresler:
            adresler.append(bicimli)
    return ", ".join(adresler)


def ek_icerik_turu_bul(dosya_adi):
    ctype, encoding = mimetypes.guess_type(dosya_adi or "")
    if ctype is None or encoding is not None or "/" not in ctype:
        ctype = "application/octet-stream"
    return ctype.split("/", 1)


def mesaj_metni_ve_ekleri_cikar(mesaj):
    duz_metinler = []
    html_metinler = []
    ekler = []

    parcalar = mesaj.walk() if mesaj.is_multipart() else [mesaj]
    for parca in parcalar:
        try:
            icerik_turu = parca.get_content_type()
            dosya_adi = parca.get_filename()
            icerik_duzeni = str(parca.get("Content-Disposition", "")).lower()

            if dosya_adi or "attachment" in icerik_duzeni:
                veri = parca.get_payload(decode=True)
                if veri:
                    ekler.append((guvenli_coz(dosya_adi or "ek_dosya"), veri))
                continue

            if icerik_turu not in ("text/plain", "text/html"):
                continue

            veri = parca.get_payload(decode=True)
            if veri is None:
                icerik = str(parca.get_payload() or "")
            else:
                icerik = veri.decode(parca.get_content_charset() or "utf-8", errors="replace")

            if icerik_turu == "text/plain":
                duz_metinler.append(icerik)
            else:
                html_metinler.append(icerik)
        except Exception as e:
            hata_kaydet("E-posta parçası okunamadı.", e)

    duz_metin = "\n".join(metin.strip() for metin in duz_metinler if metin.strip())
    html_metin = "\n".join(metin.strip() for metin in html_metinler if metin.strip())

    if duz_metin and "<html" in duz_metin.lower():
        duz_metin = html_temizle(duz_metin)
    if not duz_metin.strip() and html_metin:
        duz_metin = html_temizle(html_metin)

    return duz_metin.strip(), ekler


def ham_mesaj_verisi_al(fetch_sonucu):
    ham = b""
    for parca in fetch_sonucu or []:
        if isinstance(parca, tuple) and len(parca) >= 2 and isinstance(parca[1], bytes):
            ham += parca[1]
    return ham


def seen_bayragi_var_mi(fetch_sonucu):
    try:
        for parca in fetch_sonucu or []:
            baslik = parca[0] if isinstance(parca, tuple) else parca
            if isinstance(baslik, bytes) and b"\\seen" in baslik.lower():
                return True
            if isinstance(baslik, str) and "\\seen" in baslik.lower():
                return True
    except Exception:
        pass
    return False


def eposta_basligi_tek_satir_yap(deger):
    deger = str(deger or "").strip()
    deger = re.sub(r"[\r\n]+", " ", deger)
    deger = re.sub(r"\s+", " ", deger).strip()
    return deger


def yanit_basliklari_hazirla(mesaj_verisi):
    message_id = eposta_basligi_tek_satir_yap(mesaj_verisi.get("message_id", ""))
    onceki_references = eposta_basligi_tek_satir_yap(mesaj_verisi.get("references", ""))

    if not message_id:
        return {}

    if onceki_references:
        parcalar = onceki_references.split()
        if message_id not in parcalar:
            references = onceki_references + " " + message_id
        else:
            references = onceki_references
    else:
        references = message_id

    return {
        "In-Reply-To": message_id,
        "References": references,
    }


def smtp_yaniti_oku(dosya):
    satirlar = []
    while True:
        satir = dosya.readline()
        if not satir:
            raise MailHatasi("SMTP sunucusundan yanıt alınamadı.")
        satirlar.append(satir)
        if len(satir) >= 4 and satir[:3].isdigit() and satir[3:4] != b"-":
            break
    kod = int(satirlar[-1][:3])
    metin = b"".join(satirlar).decode("utf-8", errors="replace")
    return kod, metin


def smtp_komut_gonder(sock, dosya, komut, beklenen_kodlar):
    if isinstance(beklenen_kodlar, int):
        beklenen_kodlar = (beklenen_kodlar,)
    sock.sendall((komut + "\r\n").encode("utf-8"))
    kod, metin = smtp_yaniti_oku(dosya)
    if kod not in beklenen_kodlar:
        raise MailHatasi("SMTP sunucusu gönderimi kabul etmedi.")
    return kod, metin


def smtp_mesaj_verisini_hazirla(mesaj):
    ham = mesaj.as_bytes(policy=SMTP)
    satirlar = ham.splitlines(keepends=True)
    guvenli_satirlar = []
    for satir in satirlar:
        if satir.startswith(b"."):
            guvenli_satirlar.append(b"." + satir)
        else:
            guvenli_satirlar.append(satir)
    sonuc = b"".join(guvenli_satirlar)
    if not sonuc.endswith(b"\r\n"):
        sonuc += b"\r\n"
    return sonuc + b".\r\n"


def smtp_ssl_ile_gonder(eposta, sifre, alicilar, mesaj):
    sock = None
    dosya = None
    try:
        ctx = ssl.create_default_context()
        ham_soket = socket.create_connection((GMAIL_SMTP_SUNUCU, GMAIL_SMTP_PORT), timeout=BAGLANTI_ZAMAN_ASIMI)
        sock = ctx.wrap_socket(ham_soket, server_hostname=GMAIL_SMTP_SUNUCU)
        dosya = sock.makefile("rb")

        kod, _metin = smtp_yaniti_oku(dosya)
        if kod != 220:
            raise MailHatasi("SMTP sunucusuna bağlanılamadı.")

        smtp_komut_gonder(sock, dosya, "EHLO engelsiz-mail", 250)
        smtp_komut_gonder(sock, dosya, "AUTH LOGIN", 334)
        smtp_komut_gonder(sock, dosya, base64.b64encode(eposta.encode("utf-8")).decode("ascii"), 334)
        smtp_komut_gonder(sock, dosya, base64.b64encode(sifre.encode("utf-8")).decode("ascii"), 235)
        smtp_komut_gonder(sock, dosya, f"MAIL FROM:<{eposta}>", 250)
        for alici in alicilar:
            smtp_komut_gonder(sock, dosya, f"RCPT TO:<{alici}>", (250, 251))
        smtp_komut_gonder(sock, dosya, "DATA", 354)
        sock.sendall(smtp_mesaj_verisini_hazirla(mesaj))
        kod, _metin = smtp_yaniti_oku(dosya)
        if kod != 250:
            raise MailHatasi("SMTP sunucusu mesajı kabul etmedi.")
        try:
            smtp_komut_gonder(sock, dosya, "QUIT", 221)
        except Exception:
            pass
    finally:
        try:
            if dosya:
                dosya.close()
        except Exception:
            pass
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def yardim_belgesini_ac():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    adaylar = [
        os.path.join(base_dir, "doc", "tr", "readme.html"),
        os.path.join(base_dir, "doc", "en", "readme.html"),
        os.path.join(base_dir, "doc", "readme.html"),
        os.path.join(base_dir, "yardim.html"),
    ]
    for yol in adaylar:
        if os.path.exists(yol):
            try:
                os.startfile(yol)
                return True
            except Exception as e:
                hata_kaydet("Yardım dosyası açılamadı.", e)
                break
    ui.message("Yardım dosyası bulunamadı. Lütfen eklenti klasörünü kontrol edin.")
    return False


class AyarlarPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - Google Hesabına Bağlan")
        ayarlar = ayarlari_yukle()
        self._baglanti_kontrol_ediliyor = False

        duzen = wx.BoxSizer(wx.VERTICAL)

        duzen.Add(wx.StaticText(self, label="&E-posta adresiniz:"), 0, wx.ALL, 5)
        self.txt_eposta = wx.TextCtrl(self, value=ayarlar.get("eposta", ""))
        duzen.Add(self.txt_eposta, 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="&Google uygulama şifreniz (16 hane):"), 0, wx.ALL, 5)
        self.txt_sifre = wx.TextCtrl(self, value=ayarlar.get("sifre", ""), style=wx.TE_PASSWORD)
        duzen.Add(self.txt_sifre, 0, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        self.kaydet_btn = wx.Button(self, label="&Kaydet ve Bağlan")
        self.kaydet_btn.Bind(wx.EVT_BUTTON, self.kaydet_basildi)
        btn_duzen.Add(self.kaydet_btn, 0, wx.ALL, 5)

        yardim_btn = wx.Button(self, label="Uygulama Şifresi İçin &Yardım Belgesi")
        yardim_btn.Bind(wx.EVT_BUTTON, self.yardim_basildi)
        btn_duzen.Add(yardim_btn, 0, wx.ALL, 5)

        iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(iptal_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((650, 275))
        self.CenterOnParent()
        wx.CallAfter(self.txt_eposta.SetFocus)

    def yardim_basildi(self, event):
        yardim_belgesini_ac()

    def alanlari_etkinlestir(self, etkin=True):
        for denetim in (self.txt_eposta, self.txt_sifre, self.kaydet_btn):
            try:
                denetim.Enable(etkin)
            except Exception:
                pass

    def kaydet_basildi(self, event):
        if self._baglanti_kontrol_ediliyor:
            return

        eposta = self.txt_eposta.GetValue().strip()
        sifre = self.txt_sifre.GetValue().strip().replace(" ", "")

        if not eposta or not sifre:
            ui.message("Lütfen e-posta ve uygulama şifresi alanlarını doldurun.")
            return
        if "@" not in eposta:
            ui.message("Lütfen geçerli bir e-posta adresi yazın.")
            self.txt_eposta.SetFocus()
            return
        if len(sifre) < 12:
            ui.message("Uygulama şifresi eksik görünüyor. Lütfen Google tarafından verilen şifreyi boşluksuz yazın.")
            self.txt_sifre.SetFocus()
            return

        self._baglanti_kontrol_ediliyor = True
        self.alanlari_etkinlestir(False)
        ui.message("Bağlantı denetleniyor. Lütfen bekleyiniz.")
        arka_planda_calistir(self._baglantiyi_denetle, eposta, sifre)

    def _baglantiyi_denetle(self, eposta, sifre):
        try:
            with ImapBaglantisi({"eposta": eposta, "sifre": sifre}):
                pass
            wx.CallAfter(self._baglanti_basarili, eposta, sifre)
        except Exception as e:
            hata_kaydet("Hesap bağlantısı doğrulanamadı.", e)
            wx.CallAfter(self._baglanti_hatali)

    def _baglanti_basarili(self, eposta, sifre):
        self._baglanti_kontrol_ediliyor = False
        if ayarlari_kaydet(eposta, sifre):
            gui.messageBox(
                "Gmail bağlantısı kuruldu. E-posta adresiniz NVDA yapılandırma klasörüne, uygulama şifreniz ise Windows kullanıcı hesabınıza bağlı şifreli biçimde kaydedildi.",
                "Bağlantı Başarılı",
                wx.OK | wx.ICON_INFORMATION,
            )
            self.EndModal(wx.ID_OK)
        else:
            self.alanlari_etkinlestir(True)
            ui.message("Hesap bilgileri kaydedilemedi. Lütfen dosya izinlerini kontrol edin.")

    def _baglanti_hatali(self):
        self._baglanti_kontrol_ediliyor = False
        self.alanlari_etkinlestir(True)
        gui.messageBox(
            "Gmail hesabına bağlanılamadı. Lütfen e-posta adresinizi, Google uygulama şifrenizi ve internet bağlantınızı kontrol edin.",
            "Bağlantı Başarısız",
            wx.OK | wx.ICON_WARNING,
        )
        self.txt_sifre.SetFocus()


class MesajSayisiPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - E-Posta Sayısı")
        ayarlar = ayarlari_yukle()

        duzen = wx.BoxSizer(wx.VERTICAL)
        bilgi = f"Listelenecek e-posta sayısı ({EN_AZ_MESAJ_SAYISI} ile {EN_COK_MESAJ_SAYISI} arası):"
        duzen.Add(wx.StaticText(self, label="&" + bilgi), 0, wx.ALL, 5)
        self.txt_mesaj_sayisi = wx.TextCtrl(
            self,
            value=str(ayarlar.get(MESAJ_SAYISI_ALANI, VARSAYILAN_MESAJ_SAYISI)),
        )
        duzen.Add(self.txt_mesaj_sayisi, 0, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        tamam_btn = wx.Button(self, label="&Tamam")
        tamam_btn.Bind(wx.EVT_BUTTON, self.tamam_basildi)
        btn_duzen.Add(tamam_btn, 0, wx.ALL, 5)

        iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(iptal_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((460, 170))
        self.CenterOnParent()
        wx.CallAfter(self.txt_mesaj_sayisi.SetFocus)

    def tamam_basildi(self, event):
        try:
            mesaj_sayisi = mesaj_sayisi_metnini_dogrula(self.txt_mesaj_sayisi.GetValue())
        except MailHatasi as e:
            ui.message(str(e))
            self.txt_mesaj_sayisi.SetFocus()
            return

        if mesaj_sayisini_kaydet(mesaj_sayisi):
            ui.message(f"Listelenecek e-posta sayısı {mesaj_sayisi} olarak kaydedildi.")
            self.EndModal(wx.ID_OK)
        else:
            ui.message("E-posta sayısı kaydedilemedi. Lütfen dosya izinlerini kontrol edin.")



class OneriGorusPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - Öneri ve Görüş Bildir")
        self._gonderiliyor = False
        self.Bind(wx.EVT_CHAR_HOOK, self.tus_yakalandi)

        duzen = wx.BoxSizer(wx.VERTICAL)
        bilgi = (
            "İletişim Formu\n"
            "Her türlü öneri, görüş ve düşünceleriniz için bize yazın.\n"
            "Mesajınız değerlendirilip, en kısa süre içerisinde tarafınıza geri dönüş sağlanacaktır."
        )
        duzen.Add(wx.StaticText(self, label=bilgi), 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="&Ad:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.txt_ad = wx.TextCtrl(self)
        duzen.Add(self.txt_ad, 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="&Soyad:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.txt_soyad = wx.TextCtrl(self)
        duzen.Add(self.txt_soyad, 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="Yanıt için &e-posta adresiniz:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        duzen.Add(
            wx.StaticText(
                self,
                label="Lütfen e-posta adresinizi doğru yazdığınızdan emin olunuz."
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            5,
        )
        self.txt_eposta = wx.TextCtrl(self)
        duzen.Add(self.txt_eposta, 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="&Konu:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        duzen.Add(
            wx.StaticText(
                self,
                label="Mesajınızın konusu"
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            5,
        )
        self.txt_konu = wx.TextCtrl(self)
        duzen.Add(self.txt_konu, 0, wx.ALL | wx.EXPAND, 5)

        duzen.Add(wx.StaticText(self, label="&Mesaj:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        duzen.Add(
            wx.StaticText(
                self,
                label="Mesajınız"
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            5,
        )
        self.txt_mesaj = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_RICH2)
        duzen.Add(self.txt_mesaj, 1, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        self.gonder_btn = wx.Button(self, label="&Gönder")
        self.gonder_btn.Bind(wx.EVT_BUTTON, self.gonder_tiklandi)
        btn_duzen.Add(self.gonder_btn, 0, wx.ALL, 5)

        self.iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(self.iptal_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(duzen)
        self.SetSize((640, 560))
        self.CenterOnParent()
        wx.CallAfter(self.txt_ad.SetFocus)

    def tus_yakalandi(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if not self._gonderiliyor:
                self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def alanlari_etkinlestir(self, etkin=True):
        for denetim in (
            self.txt_ad,
            self.txt_soyad,
            self.txt_eposta,
            self.txt_konu,
            self.txt_mesaj,
            self.gonder_btn,
            self.iptal_btn,
        ):
            try:
                denetim.Enable(etkin)
            except Exception:
                pass

    def form_verisini_al(self):
        return {
            "ad": self.txt_ad.GetValue().strip(),
            "soyad": self.txt_soyad.GetValue().strip(),
            "eposta": self.txt_eposta.GetValue().strip(),
            "konu": self.txt_konu.GetValue().strip(),
            "mesaj": self.txt_mesaj.GetValue().strip(),
        }

    def formu_dogrula(self, veri):
        if not veri["ad"]:
            self.txt_ad.SetFocus()
            raise MailHatasi("Lütfen ad alanını doldurun.")
        if not veri["soyad"]:
            self.txt_soyad.SetFocus()
            raise MailHatasi("Lütfen soyad alanını doldurun.")
        if not veri["eposta"] or "@" not in veri["eposta"]:
            self.txt_eposta.SetFocus()
            raise MailHatasi("Size yanıt verilebilmesi için lütfen geçerli bir e-posta adresi yazın.")
        if not veri["konu"]:
            self.txt_konu.SetFocus()
            raise MailHatasi("Lütfen konu alanını doldurun.")
        if not veri["mesaj"]:
            self.txt_mesaj.SetFocus()
            raise MailHatasi("Lütfen mesaj alanını doldurun.")

    def gonder_tiklandi(self, event=None):
        if self._gonderiliyor:
            return
        ayarlar = ayarlari_yukle()
        if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
            gui.messageBox(
                "Öneri ve görüş göndermek için önce Dosya menüsünden Bağlan seçeneğiyle Gmail hesabınızı bağlayın.",
                "Hesap Bilgisi Eksik",
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return
        veri = self.form_verisini_al()
        try:
            self.formu_dogrula(veri)
        except MailHatasi as e:
            ui.message(str(e))
            return

        self._gonderiliyor = True
        self.alanlari_etkinlestir(False)
        ui.message("Öneri ve görüş gönderiliyor.")
        arka_planda_calistir(self.arka_planda_gonder, ayarlar, veri)

    def arka_planda_gonder(self, ayarlar, veri):
        try:
            konu = eposta_basligi_tek_satir_yap(veri.get("konu", "")) or "Konu belirtilmedi"
            baslik = f"[Engelsiz Mail] Öneri ve Görüş: {konu}"
            icerik = (
                "Engelsiz Mail eklentisi üzerinden öneri ve görüş bildirimi gönderildi.\n\n"
                f"Ad: {veri.get('ad', '')}\n"
                f"Soyad: {veri.get('soyad', '')}\n"
                f"Yanıt için e-posta: {veri.get('eposta', '')}\n"
                "Eklenti: Engelsiz Mail\n"
                f"Gönderen Gmail hesabı: {ayarlar.get('eposta', '')}\n"
                f"Konu: {konu}\n\n"
                "Mesaj:\n"
                f"{veri.get('mesaj', '')}\n"
            )
            mesaj = eposta_mesaji_olustur(
                ayarlar["eposta"],
                ONERI_GORUS_ALICI,
                baslik,
                icerik,
                [],
                ek_basliklar={"Reply-To": veri.get("eposta", "")},
                taslak=False,
            )
            smtp_ssl_ile_gonder(ayarlar["eposta"], ayarlar["sifre"], [ONERI_GORUS_ALICI], mesaj)
            guvenli_call_after(self, self.gonderim_basarili)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, self.gonderim_hatali, str(e))
        except Exception as e:
            hata_kaydet("Öneri ve görüş gönderilemedi.", e)
            guvenli_call_after(self, self.gonderim_hatali, "Öneri ve görüş gönderilemedi. Lütfen bağlantınızı ve Google uygulama şifrenizi kontrol edin.")

    def gonderim_basarili(self):
        if not pencere_kullanilabilir_mi(self):
            return
        ui.message("Öneri ve görüşünüz gönderildi.")
        self.EndModal(wx.ID_OK)

    def gonderim_hatali(self, mesaj):
        if not pencere_kullanilabilir_mi(self):
            return
        self._gonderiliyor = False
        ui.message(mesaj)
        self.alanlari_etkinlestir(True)
        self.txt_mesaj.SetFocus()

def eposta_mesaji_olustur(gonderen, kime_basligi, konu, icerik, ek_kayitlari, ek_basliklar=None, taslak=False):
    """Gönderim veya taslak kaydı için MIME ileti oluşturur."""
    mesaj = EmailMessage(policy=SMTP)
    mesaj["From"] = gonderen
    kime_basligi = str(kime_basligi or "").strip()
    if kime_basligi:
        mesaj["To"] = kime_basligi
    mesaj["Subject"] = str(konu or "").strip() or "Konusuz"

    if taslak:
        mesaj["Date"] = email.utils.formatdate(localtime=True)
        mesaj["Message-ID"] = email.utils.make_msgid()
        mesaj["X-Unsent"] = "1"

    for baslik_adi, baslik_degeri in (ek_basliklar or {}).items():
        baslik_degeri = eposta_basligi_tek_satir_yap(baslik_degeri)
        if baslik_adi and baslik_degeri and baslik_adi not in mesaj:
            mesaj[baslik_adi] = baslik_degeri

    mesaj.set_content(icerik or "")

    for kayit in ek_kayitlari or []:
        if isinstance(kayit, str):
            kayit = {"tur": "dosya", "yol": kayit}
        tur = kayit.get("tur")
        if tur == "hazir":
            dosya_adi = guvenli_coz(kayit.get("ad") or "ek_dosya")
            veri = kayit.get("veri") or b""
            if not veri:
                continue
            maintype, subtype = ek_icerik_turu_bul(dosya_adi)
            mesaj.add_attachment(veri, maintype=maintype, subtype=subtype, filename=dosya_adi)
            continue

        dosya_yolu = kayit.get("yol", "")
        if not os.path.isfile(dosya_yolu):
            raise MailHatasi(f"Ek dosya bulunamadı: {os.path.basename(dosya_yolu)}")
        maintype, subtype = ek_icerik_turu_bul(dosya_yolu)
        with open(dosya_yolu, "rb") as dosya:
            mesaj.add_attachment(
                dosya.read(),
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(dosya_yolu),
            )
    return mesaj


def taslak_klasor_adaylarini_temizle(adaylar=None):
    temiz = []

    def ekle(deger):
        deger = str(deger or "").strip()
        if deger and deger not in temiz:
            temiz.append(deger)

    for aday in adaylar or []:
        ekle(aday)
    ekle(VARSAYILAN_KLASOR_HARITASI.get("Taslaklar"))
    ekle('"[Gmail]/Drafts"')
    ekle('"[Google Mail]/Drafts"')
    ekle(imap_klasor_adi_hazirla("Taslaklar"))
    ekle(imap_klasor_adi_hazirla("Drafts"))
    return temiz


def taslagi_sunucuya_kaydet(kime, konu, icerik, ek_kayitlari, yanit_basliklari=None, taslak_klasor_adaylari=None):
    """İletiyi Gmail Taslaklar klasörüne kaydeder."""
    ayarlar = ayarlari_yukle()
    if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
        raise MailHatasi("Hesap bilgileri eksik.")

    mesaj = eposta_mesaji_olustur(
        ayarlar["eposta"],
        kime,
        konu,
        icerik,
        ek_kayitlari,
        ek_basliklar=yanit_basliklari,
        taslak=True,
    )
    ham_mesaj = mesaj.as_bytes(policy=SMTP)

    son_hata = ""
    with ImapBaglantisi(ayarlar) as imap:
        for aday_klasor in taslak_klasor_adaylarini_temizle(taslak_klasor_adaylari):
            try:
                tip, _veri = imap.append(aday_klasor, "(\\Draft)", None, ham_mesaj)
                if tip == "OK":
                    return True
                son_hata = f"Taslak klasörü kabul etmedi: {aday_klasor}"
            except Exception as e:
                son_hata = f"Taslak kaydetme denemesi başarısız: {aday_klasor}"
                hata_kaydet(son_hata, e)
                continue

    raise MailHatasi("Taslak Gmail Taslaklar klasörüne kaydedilemedi.")


class YeniPostaPenceresi(wx.Dialog):
    def __init__(
        self,
        parent,
        varsayilan_kime="",
        varsayilan_konu="",
        varsayilan_icerik="",
        yanit_basliklari=None,
        baslik="Engelsiz Mail - Posta Yaz",
        gonderildi_callback=None,
        taslak_sil_callback=None,
        taslak_kaydet_callback=None,
        taslak_klasor_adaylari=None,
        hazir_ekler=None,
    ):
        super().__init__(parent, title=baslik)
        self.ek_kayitlari = []
        self.yanit_basliklari = dict(yanit_basliklari or {})
        self.gonderildi_callback = gonderildi_callback
        self.taslak_sil_callback = taslak_sil_callback
        self.taslak_kaydet_callback = taslak_kaydet_callback
        self.taslak_klasor_adaylari = taslak_klasor_adaylarini_temizle(taslak_klasor_adaylari)
        self._kapatildi = False
        self._taslak_kaydediliyor = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._pencere_yok_ediliyor)
        self.Bind(wx.EVT_CHAR_HOOK, self.tus_yakalandi)

        self.ana_duzen = wx.BoxSizer(wx.VERTICAL)

        kime_duzen = wx.BoxSizer(wx.HORIZONTAL)
        kime_duzen.Add(wx.StaticText(self, label="&Kime (e-posta adresi):"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        gecmis_adresler = rehberi_yukle()
        if varsayilan_kime and varsayilan_kime not in gecmis_adresler:
            gecmis_adresler.insert(0, varsayilan_kime)
        self.txt_kime = wx.ComboBox(self, value=varsayilan_kime, choices=gecmis_adresler, style=wx.CB_DROPDOWN)
        kime_duzen.Add(self.txt_kime, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(kime_duzen, 0, wx.EXPAND)

        konu_duzen = wx.BoxSizer(wx.HORIZONTAL)
        konu_duzen.Add(wx.StaticText(self, label="K&onu:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.txt_konu = wx.TextCtrl(self, value=varsayilan_konu)
        konu_duzen.Add(self.txt_konu, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(konu_duzen, 0, wx.EXPAND)

        self.ana_duzen.Add(wx.StaticText(self, label="&Mesajınız:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.txt_icerik = wx.TextCtrl(self, value=varsayilan_icerik, style=wx.TE_MULTILINE | wx.TE_RICH2)
        self.ana_duzen.Add(self.txt_icerik, 1, wx.ALL | wx.EXPAND, 5)

        ek_duzen = wx.BoxSizer(wx.HORIZONTAL)
        ek_duzen.Add(wx.StaticText(self, label="Ekli &dosyalar:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.liste_ekler = wx.ListBox(self, style=wx.LB_SINGLE, size=(-1, 60))
        ek_duzen.Add(self.liste_ekler, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(ek_duzen, 0, wx.EXPAND)

        for dosya_adi, veri in hazir_ekler or []:
            if veri:
                self.ek_kayitlari.append({"tur": "hazir", "ad": guvenli_coz(dosya_adi or "ek_dosya"), "veri": veri})
                self.liste_ekler.Append(guvenli_coz(dosya_adi or "ek_dosya"))

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        self.ek_ekle_btn = wx.Button(self, label="Dosya e&kle")
        self.ek_ekle_btn.Bind(wx.EVT_BUTTON, self.dosya_ekle)
        btn_duzen.Add(self.ek_ekle_btn, 0, wx.ALL, 5)

        self.ek_kaldir_btn = wx.Button(self, label="Eki k&aldır")
        self.ek_kaldir_btn.Bind(wx.EVT_BUTTON, self.ek_kaldir)
        btn_duzen.Add(self.ek_kaldir_btn, 0, wx.ALL, 5)

        self.gonder_btn = wx.Button(self, label="&Gönder")
        self.gonder_btn.Bind(wx.EVT_BUTTON, self.gonder_tiklandi)
        btn_duzen.Add(self.gonder_btn, 0, wx.ALL, 5)

        self.taslak_kaydet_btn = wx.Button(self, label="Taslaklara &Kaydet")
        self.taslak_kaydet_btn.Bind(wx.EVT_BUTTON, self.taslak_kaydet_tiklandi)
        btn_duzen.Add(self.taslak_kaydet_btn, 0, wx.ALL, 5)

        if self.taslak_sil_callback:
            self.taslak_sil_btn = wx.Button(self, label="Taslağı &Sil")
            self.taslak_sil_btn.Bind(wx.EVT_BUTTON, self.taslagi_sil)
            btn_duzen.Add(self.taslak_sil_btn, 0, wx.ALL, 5)
        else:
            self.taslak_sil_btn = None

        kapat_btn = wx.Button(self, label="İ&ptal")
        kapat_btn.Bind(wx.EVT_BUTTON, self.iptal_tiklandi)
        btn_duzen.Add(kapat_btn, 0, wx.ALL, 5)

        self.ana_duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(self.ana_duzen)
        self.SetSize((760, 650))
        self.CenterOnParent()

        self._baslangic_durumu = self.taslak_durumu_al()

        if varsayilan_kime:
            wx.CallAfter(self.txt_icerik.SetFocus)
            wx.CallAfter(self.txt_icerik.SetInsertionPoint, 0)
        else:
            wx.CallAfter(self.txt_kime.SetFocus)

    def _pencere_yok_ediliyor(self, event):
        if event.GetEventObject() is self:
            self._kapatildi = True
        event.Skip()

    def dosya_ekle(self, event):
        dlg = wx.FileDialog(
            self,
            "Eklenecek dosyaları seçin",
            "",
            "",
            "*.*",
            wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                eklenen_sayi = 0
                mevcut_yollar = {kayit.get("yol") for kayit in self.ek_kayitlari if kayit.get("tur") == "dosya"}
                for yol in dlg.GetPaths():
                    if yol not in mevcut_yollar:
                        self.ek_kayitlari.append({"tur": "dosya", "yol": yol})
                        self.liste_ekler.Append(os.path.basename(yol))
                        mevcut_yollar.add(yol)
                        eklenen_sayi += 1
                if eklenen_sayi:
                    ui.message(f"{eklenen_sayi} dosya eklendi.")
                wx.CallAfter(self.liste_ekler.SetFocus)
            else:
                wx.CallAfter(self.txt_icerik.SetFocus)
        finally:
            dlg.Destroy()

    def ek_kaldir(self, event):
        secili_indeks = self.liste_ekler.GetSelection()
        if secili_indeks == wx.NOT_FOUND:
            ui.message("Lütfen kaldırmak istediğiniz eki listeden seçin.")
            self.liste_ekler.SetFocus()
            return
        silinen_isim = self.liste_ekler.GetString(secili_indeks)
        del self.ek_kayitlari[secili_indeks]
        self.liste_ekler.Delete(secili_indeks)
        ui.message(f"Ek kaldırıldı: {silinen_isim}")
        if self.liste_ekler.GetCount() > 0:
            self.liste_ekler.SetSelection(min(secili_indeks, self.liste_ekler.GetCount() - 1))
        self.liste_ekler.SetFocus()

    def taslagi_sil(self, event):
        if not self.taslak_sil_callback:
            return
        try:
            if self.taslak_sil_callback():
                self.EndModal(wx.ID_OK)
        except Exception as e:
            hata_kaydet("Taslak silme isteği başlatılamadı.", e)
            ui.message("Taslak silme işlemi başlatılamadı.")

    def alanlari_etkinlestir(self, etkin=True):
        denetimler = [
            self.txt_kime,
            self.txt_konu,
            self.txt_icerik,
            self.gonder_btn,
            self.taslak_kaydet_btn,
            self.ek_ekle_btn,
            self.ek_kaldir_btn,
            self.liste_ekler,
        ]
        if self.taslak_sil_btn:
            denetimler.append(self.taslak_sil_btn)
        for denetim in denetimler:
            try:
                denetim.Enable(etkin)
            except Exception:
                pass

    def tus_yakalandi(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.iptal_tiklandi(event)
            return
        event.Skip()

    def taslak_durumu_al(self):
        ekler = []
        for kayit in self.ek_kayitlari:
            if isinstance(kayit, str):
                ekler.append(("dosya", kayit))
            elif kayit.get("tur") == "hazir":
                ekler.append(("hazir", kayit.get("ad", ""), len(kayit.get("veri") or b"")))
            else:
                ekler.append((kayit.get("tur", ""), kayit.get("yol", "")))
        return (
            self.txt_kime.GetValue().strip(),
            self.txt_konu.GetValue().strip(),
            self.txt_icerik.GetValue(),
            tuple(ekler),
        )

    def taslak_icerigi_var_mi(self):
        kime, konu, icerik, ekler = self.taslak_durumu_al()
        return bool(kime or konu or str(icerik or "").strip() or ekler)

    def taslak_degisti_mi(self):
        return self.taslak_durumu_al() != getattr(self, "_baslangic_durumu", None)

    def taslak_verisini_al(self):
        return {
            "kime": self.txt_kime.GetValue().strip(),
            "konu": self.txt_konu.GetValue().strip(),
            "icerik": self.txt_icerik.GetValue(),
            "ek_kayitlari": list(self.ek_kayitlari),
            "yanit_basliklari": dict(self.yanit_basliklari),
        }

    def iptal_tiklandi(self, event=None):
        if self._taslak_kaydediliyor:
            ui.message("Taslak kaydediliyor. Lütfen işlemin tamamlanmasını bekleyin.")
            return
        if not self.taslak_icerigi_var_mi() or not self.taslak_degisti_mi():
            self.EndModal(wx.ID_CANCEL)
            return

        sonuc = gui.messageBox(
            "Bu e-posta gönderilmedi. Değişiklikler taslaklara kaydedilsin mi?",
            "Taslak Kaydet",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
            self,
        )
        if sonuc == wx.YES:
            self.taslak_kaydet_tiklandi(event)
        elif sonuc == wx.NO:
            self.EndModal(wx.ID_CANCEL)
        else:
            self.txt_icerik.SetFocus()

    def taslak_kaydet_tiklandi(self, event=None):
        if not self.taslak_icerigi_var_mi():
            ui.message("Kaydedilecek taslak içeriği bulunamadı.")
            self.txt_icerik.SetFocus()
            return
        veri = self.taslak_verisini_al()
        ui.message("Taslaklara kaydediliyor.")
        self._taslak_kaydediliyor = True
        self.alanlari_etkinlestir(False)
        arka_planda_calistir(self.arka_planda_taslak_kaydet, veri)

    def arka_planda_taslak_kaydet(self, veri):
        try:
            taslagi_sunucuya_kaydet(
                veri.get("kime", ""),
                veri.get("konu", ""),
                veri.get("icerik", ""),
                veri.get("ek_kayitlari", []),
                veri.get("yanit_basliklari", {}),
                self.taslak_klasor_adaylari,
            )
            guvenli_call_after(self, self.taslak_kaydetme_basarili)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, self.taslak_kaydetme_hatali, str(e))
        except Exception as e:
            hata_kaydet("Taslak kaydedilemedi.", e)
            guvenli_call_after(self, self.taslak_kaydetme_hatali, "Taslak kaydedilemedi. Lütfen bağlantınızı ve Google uygulama şifrenizi kontrol edin.")

    def taslak_kaydetme_basarili(self):
        if not pencere_kullanilabilir_mi(self):
            return
        callback_sonucu = False
        if self.taslak_kaydet_callback:
            try:
                callback_sonucu = bool(self.taslak_kaydet_callback())
            except Exception as e:
                hata_kaydet("Taslak kaydetme sonrası işlem başlatılamadı.", e)
        if callback_sonucu:
            ui.message("Taslaklara kaydedildi. Eski taslak kaldırılıyor.")
        else:
            ui.message("Taslaklara kaydedildi.")
        self.EndModal(wx.ID_OK)

    def taslak_kaydetme_hatali(self, mesaj):
        if not pencere_kullanilabilir_mi(self):
            return
        self._taslak_kaydediliyor = False
        ui.message(mesaj)
        self.alanlari_etkinlestir(True)
        self.txt_icerik.SetFocus()

    def gonder_tiklandi(self, event):
        kime = self.txt_kime.GetValue().strip()
        konu = self.txt_konu.GetValue().strip()
        icerik = self.txt_icerik.GetValue()
        alicilar = alici_listesi_yap(kime)

        if not alicilar:
            ui.message("Lütfen geçerli en az bir alıcı adresi girin.")
            self.txt_kime.SetFocus()
            return

        rehbere_ekle(kime)
        ui.message("E-postanız gönderiliyor.")
        self.alanlari_etkinlestir(False)
        arka_planda_calistir(self.arka_planda_gonder, kime, konu, icerik, alicilar, list(self.ek_kayitlari), dict(self.yanit_basliklari))

    def arka_planda_gonder(self, kime, konu, icerik, alicilar, ek_kayitlari, yanit_basliklari=None):
        ayarlar = ayarlari_yukle()
        try:
            if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
                raise MailHatasi("Hesap bilgileri eksik.")

            mesaj = eposta_mesaji_olustur(
                ayarlar["eposta"],
                ", ".join(alicilar),
                konu,
                icerik,
                ek_kayitlari,
                ek_basliklar=yanit_basliklari,
                taslak=False,
            )

            smtp_ssl_ile_gonder(ayarlar["eposta"], ayarlar["sifre"], alicilar, mesaj)
            guvenli_call_after(self, self.gonderim_basarili)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, self.gonderim_hatali, str(e))
        except Exception as e:
            hata_kaydet("E-posta gönderilemedi.", e)
            guvenli_call_after(self, self.gonderim_hatali, "Gönderim başarısız oldu. Lütfen bağlantınızı ve Google uygulama şifrenizi kontrol edin.")

    def gonderim_basarili(self):
        if not pencere_kullanilabilir_mi(self):
            return
        callback_sonucu = False
        if self.gonderildi_callback:
            try:
                callback_sonucu = bool(self.gonderildi_callback())
            except Exception as e:
                hata_kaydet("Gönderim sonrası işlem başlatılamadı.", e)
        if callback_sonucu:
            ui.message("E-posta başarıyla gönderildi. Taslak kaldırılıyor.")
        else:
            ui.message("E-posta başarıyla gönderildi.")
        self.EndModal(wx.ID_OK)

    def gonderim_hatali(self, mesaj):
        if not pencere_kullanilabilir_mi(self):
            return
        ui.message(mesaj)
        self.alanlari_etkinlestir(True)
        self.txt_icerik.SetFocus()


class ArsivSecimPenceresi(wx.Dialog):
    def __init__(self, parent, ozel_klasorler, ebeveyn_pencere):
        super().__init__(parent, title="Engelsiz Mail - Arşive Gönderme")
        self.secilen_isim = None
        self.ebeveyn = ebeveyn_pencere

        duzen = wx.BoxSizer(wx.VERTICAL)
        duzen.Add(wx.StaticText(self, label="&Hedef arşivi seçin:"), 0, wx.ALL, 5)

        secenekler = [YENI_ARSIV_SECENEGI] + list(ozel_klasorler)
        self.liste_kutu = wx.ListBox(self, choices=secenekler, style=wx.LB_SINGLE)
        self.liste_kutu.SetSelection(0)
        duzen.Add(self.liste_kutu, 1, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        tamam_btn = wx.Button(self, label="&Tamam")
        tamam_btn.Bind(wx.EVT_BUTTON, self.tamam_basildi)
        btn_duzen.Add(tamam_btn, 0, wx.ALL, 5)

        sil_btn = wx.Button(self, label="Seçili arşiv klasörünü s&il")
        sil_btn.Bind(wx.EVT_BUTTON, self.sil_basildi)
        btn_duzen.Add(sil_btn, 0, wx.ALL, 5)

        iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(iptal_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((560, 320))
        self.CenterOnParent()
        wx.CallAfter(self.liste_kutu.SetFocus)

    def tamam_basildi(self, event):
        secim = self.liste_kutu.GetSelection()
        if secim != wx.NOT_FOUND:
            self.secilen_isim = self.liste_kutu.GetString(secim)
            self.EndModal(wx.ID_OK)

    def sil_basildi(self, event):
        secim = self.liste_kutu.GetSelection()
        if secim == wx.NOT_FOUND:
            ui.message("Lütfen silmek istediğiniz arşivi seçin.")
            return
        isim = self.liste_kutu.GetString(secim)
        if isim == YENI_ARSIV_SECENEGI:
            ui.message("Bu seçenek silinemez.")
            self.liste_kutu.SetFocus()
            return
        cevap = gui.messageBox(
            f"'{isim}' adlı arşiv klasörünü silmek istiyor musunuz?",
            "Arşiv Silme Onayı",
            wx.YES_NO | wx.ICON_WARNING,
        )
        if cevap == wx.YES:
            self.ebeveyn.arsiv_klasoru_sil(isim)
            self.EndModal(wx.ID_CANCEL)


class YeniKlasorPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - Yeni Arşiv Klasörü")
        self.klasor_adi = None

        duzen = wx.BoxSizer(wx.VERTICAL)
        duzen.Add(wx.StaticText(self, label="&Yeni arşiv klasörünün adını yazın:"), 0, wx.ALL, 5)
        self.txt_isim = wx.TextCtrl(self)
        duzen.Add(self.txt_isim, 0, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        olustur_btn = wx.Button(self, label="&Oluştur")
        olustur_btn.Bind(wx.EVT_BUTTON, self.tamam_basildi)
        btn_duzen.Add(olustur_btn, 0, wx.ALL, 5)

        iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(iptal_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((420, 180))
        self.CenterOnParent()
        wx.CallAfter(self.txt_isim.SetFocus)

    def tamam_basildi(self, event):
        isim = self.txt_isim.GetValue().strip()
        if not isim:
            ui.message("Lütfen bir klasör adı yazın.")
            self.txt_isim.SetFocus()
            return
        self.klasor_adi = isim
        self.EndModal(wx.ID_OK)


class MesajOkumaPenceresi(wx.Dialog):
    def __init__(self, parent, mesaj_verisi, ebeveyn_pencere):
        super().__init__(parent, title="Engelsiz Mail - Mesaj Görüntüleme")
        self.mesaj_verisi = mesaj_verisi
        self.ebeveyn = ebeveyn_pencere
        self._kapatildi = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._pencere_yok_ediliyor)
        self.Bind(wx.EVT_CHAR_HOOK, self.tus_yakalandi)

        duzen = wx.BoxSizer(wx.VERTICAL)
        ek_sayisi = len(mesaj_verisi.get("ekler", []))
        ek_notu = f"\nBu mesajda {ek_sayisi} ek dosya var.\n" if ek_sayisi else ""
        icerik = (
            f"Kimden: {mesaj_verisi.get('kimden_tam', '')}\n"
            f"Tarih: {mesaj_verisi.get('tarih', '')}\n"
            f"Konu: {mesaj_verisi.get('konu', '')}\n"
            f"{ek_notu}{'-' * 50}\n\n"
            f"{mesaj_verisi.get('icerik', '')}"
        )
        self.txt_icerik = wx.TextCtrl(self, value=icerik, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        duzen.Add(self.txt_icerik, 1, wx.ALL | wx.EXPAND, 10)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        if ek_sayisi:
            ek_btn = wx.Button(self, label=f"&Ekleri Kaydet ({ek_sayisi})")
            ek_btn.Bind(wx.EVT_BUTTON, self.ekleri_kaydet)
            btn_duzen.Add(ek_btn, 0, wx.ALL, 5)

        yanitla_btn = wx.Button(self, label="&Yanıtla")
        yanitla_btn.Bind(wx.EVT_BUTTON, self.mesaji_yanitla)
        btn_duzen.Add(yanitla_btn, 0, wx.ALL, 5)

        ilet_btn = wx.Button(self, label="İ&let")
        ilet_btn.Bind(wx.EVT_BUTTON, self.mesaji_ilet)
        btn_duzen.Add(ilet_btn, 0, wx.ALL, 5)

        arsiv_btn = wx.Button(self, label="A&rşivle")
        arsiv_btn.Bind(wx.EVT_BUTTON, self.mesaji_arsivle_ve_kapat)
        btn_duzen.Add(arsiv_btn, 0, wx.ALL, 5)

        sil_btn = wx.Button(self, label="&Sil")
        sil_btn.Bind(wx.EVT_BUTTON, self.mesaji_sil_ve_kapat)
        btn_duzen.Add(sil_btn, 0, wx.ALL, 5)

        kapat_btn = wx.Button(self, label="&Kapat")
        kapat_btn.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_OK))
        btn_duzen.Add(kapat_btn, 0, wx.ALL, 5)

        duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(duzen)
        self.SetSize((860, 660))
        self.CenterOnParent()
        wx.CallAfter(self.txt_icerik.SetFocus)

    def _pencere_yok_ediliyor(self, event):
        if event.GetEventObject() is self:
            self._kapatildi = True
        event.Skip()

    def tus_yakalandi(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
            return
        event.Skip()

    def ekleri_kaydet(self, event):
        konu = guvenli_dosya_adi(self.mesaj_verisi.get("konu", "Konusuz"), "Konusuz")
        hedef_klasor = os.path.join(os.path.expanduser("~"), "Downloads", f"Mail_Ekleri_{konu}")
        try:
            os.makedirs(hedef_klasor, exist_ok=True)
            kaydedilen = 0
            for dosya_adi, veri in self.mesaj_verisi.get("ekler", []):
                if not veri:
                    continue
                temiz_ad = guvenli_dosya_adi(dosya_adi, "ek_dosya")
                hedef_yol = benzersiz_yol(hedef_klasor, temiz_ad)
                with open(hedef_yol, "wb") as dosya:
                    dosya.write(veri)
                kaydedilen += 1
            if kaydedilen:
                ui.message(f"{kaydedilen} ek dosya İndirilenler klasörüne kaydedildi.")
            else:
                ui.message("Kaydedilecek ek dosya bulunamadı.")
        except Exception as e:
            hata_kaydet("Ek dosyalar kaydedilemedi.", e)
            ui.message("Ekler kaydedilemedi. Lütfen dosya izinlerini kontrol edin.")

    def mesaji_yanitla(self, event):
        kime = self.mesaj_verisi.get("kimden_adres", "")
        konu = self.mesaj_verisi.get("konu", "")
        if not konu.lower().startswith("re:"):
            konu = "Re: " + konu
        icerik = f"\n\n\n--- Orijinal Mesaj ---\n{self.mesaj_verisi.get('icerik', '')}"
        pencere = YeniPostaPenceresi(
            self,
            varsayilan_kime=kime,
            varsayilan_konu=konu,
            varsayilan_icerik=icerik,
            yanit_basliklari=yanit_basliklari_hazirla(self.mesaj_verisi),
            taslak_kaydet_callback=lambda: self.ebeveyn.taslak_kaydedildi(),
            taslak_klasor_adaylari=self.ebeveyn.taslak_klasor_adaylari(),
        )
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.txt_icerik.SetFocus)

    def mesaji_ilet(self, event):
        konu = self.mesaj_verisi.get("konu", "")
        if not konu.lower().startswith("fwd:"):
            konu = "Fwd: " + konu
        icerik = f"\n\n\n--- İletilen Mesaj ---\n{self.mesaj_verisi.get('icerik', '')}"
        pencere = YeniPostaPenceresi(
            self,
            varsayilan_kime="",
            varsayilan_konu=konu,
            varsayilan_icerik=icerik,
            taslak_kaydet_callback=lambda: self.ebeveyn.taslak_kaydedildi(),
            taslak_klasor_adaylari=self.ebeveyn.taslak_klasor_adaylari(),
        )
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.txt_icerik.SetFocus)

    def mesaji_arsivle_ve_kapat(self, event):
        self.EndModal(wx.ID_OK)
        guvenli_call_after(
            self.ebeveyn,
            self.ebeveyn.arsiv_secim_goster,
            [self.mesaj_verisi["id"]],
            self.mesaj_verisi.get("klasor"),
        )

    def mesaji_sil_ve_kapat(self, event):
        if self.ebeveyn.tek_mesaj_sil(
            self.mesaj_verisi["id"],
            self.mesaj_verisi.get("klasor"),
        ):
            self.EndModal(wx.ID_OK)


class GelenKutusuPenceresi(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail")
        self.mailler = []
        self.isaretliler = set()
        self.ozel_klasorler = []
        self.kategori_isimleri = list(SISTEM_KLASORLERI)
        self.klasor_haritasi = dict(VARSAYILAN_KLASOR_HARITASI)
        self.secili_kategori = "Gelen Kutusu"
        self.yuklu_kategori = self.secili_kategori
        self.bekleyen_kategori = self.secili_kategori
        self.klasor_secimi_programatik = False
        self.yukleniyor = False
        self.ilk_yukleme = True
        self._yenileme_hedef_mail_id = None
        self._yenileme_hedef_indeks = None
        self._yenileme_sessiz = False
        self._kapatildi = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._pencere_yok_ediliyor)

        self.id_hesap_baglan = wx.NewId()
        self.id_yeni = wx.NewId()
        self.id_cikis = wx.NewId()
        self.id_tumunu = wx.NewId()
        self.id_kaldir = wx.NewId()
        self.id_arsiv = wx.NewId()
        self.id_sil = wx.NewId()
        self.id_yenile = wx.NewId()
        self.id_eposta_sayisi = wx.NewId()
        self.id_yardim_kilavuzu = wx.NewId()
        self.id_oneri_gorus = wx.NewId()

        self.Bind(wx.EVT_MENU, self.hesap_baglan, id=self.id_hesap_baglan)
        self.Bind(wx.EVT_MENU, self.yeni_posta_yaz, id=self.id_yeni)
        self.Bind(wx.EVT_MENU, self.pencereyi_kapat, id=self.id_cikis)
        self.Bind(wx.EVT_CLOSE, self.pencereyi_kapat)
        self.Bind(wx.EVT_MENU, self.tumunu_isaretle, id=self.id_tumunu)
        self.Bind(wx.EVT_MENU, self.isaretleri_kaldir, id=self.id_kaldir)
        self.Bind(wx.EVT_MENU, self.arsive_gonder_menu, id=self.id_arsiv)
        self.Bind(wx.EVT_MENU, self.posta_sil, id=self.id_sil)
        self.Bind(wx.EVT_MENU, self.listeyi_yenile, id=self.id_yenile)
        self.Bind(wx.EVT_MENU, self.eposta_sayisi_ayari_ac, id=self.id_eposta_sayisi)
        self.Bind(wx.EVT_MENU, self.yardim_kilavuzunu_ac, id=self.id_yardim_kilavuzu)
        self.Bind(wx.EVT_MENU, self.oneri_gorus_ac, id=self.id_oneri_gorus)

        self.menuleri_olustur()

        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [
                    (wx.ACCEL_ALT, ord("N"), self.id_yeni),
                    (wx.ACCEL_ALT, wx.WXK_F4, self.id_cikis),
                    (wx.ACCEL_ALT, ord("A"), self.id_tumunu),
                    (wx.ACCEL_ALT, ord("D"), self.id_kaldir),
                    (wx.ACCEL_ALT, ord("R"), self.id_arsiv),
                    (wx.ACCEL_ALT, ord("S"), self.id_sil),
                    (wx.ACCEL_NORMAL, wx.WXK_F5, self.id_yenile),
                ]
            )
        )

        # wx.Frame üzerinde doğru Tab dolaşımı için denetimler doğrudan Frame'e değil,
        # ayrı bir panele yerleştirilir.
        self.ana_panel = wx.Panel(self)
        self.ana_duzen = wx.BoxSizer(wx.VERTICAL)
        ust = wx.BoxSizer(wx.HORIZONTAL)
        ust.Add(wx.StaticText(self.ana_panel, label="E-posta klasörleri:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.k_kutu = wx.Choice(self.ana_panel, choices=self.kategori_isimleri)
        self.k_kutu.SetName("E-posta klasörleri")
        self.k_kutu.SetSelection(0)
        self.k_kutu.Bind(wx.EVT_CHOICE, self.kategori_degisti)
        self.k_kutu.Bind(wx.EVT_SET_FOCUS, self.klasor_secimine_odaklandi)
        ust.Add(self.k_kutu, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(ust, 0, wx.EXPAND)

        self.liste = wx.ListCtrl(self.ana_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.liste.InsertColumn(0, "Kimden", width=260)
        self.liste.InsertColumn(1, "Konu", width=430)
        self.liste.InsertItem(0, "E-postalarınız yükleniyor...")
        self.liste.Bind(wx.EVT_SET_FOCUS, self.listeye_odaklandi)
        self.liste.Bind(wx.EVT_KEY_DOWN, self.tusa_basildi)
        self.liste.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.mesaj_oku)
        self.liste.Bind(wx.EVT_CONTEXT_MENU, self.sag_tik_menusu)
        self.ana_duzen.Add(self.liste, 1, wx.ALL | wx.EXPAND, 5)


        self.ana_panel.SetSizer(self.ana_duzen)
        self.SetSize((1050, 590))
        self.CenterOnParent()
        if self.hesap_bilgisi_var_mi():
            self.verileri_yukle_tetikle("Gelen Kutusu yükleniyor...", kategori_adi=self.secili_kategori)
            wx.CallAfter(self.liste.SetFocus)
        else:
            self.hesap_bilgisi_eksik_goster()
            wx.CallAfter(self.liste.SetFocus)

    def menuleri_olustur(self):
        menu_bar = wx.MenuBar()

        dosya_menu = wx.Menu()
        dosya_menu.Append(self.id_hesap_baglan, "&Bağlan...")
        dosya_menu.Append(self.id_yeni, "&Yeni Posta Yaz\tAlt+N")
        dosya_menu.AppendSeparator()
        dosya_menu.Append(self.id_cikis, "&Çıkış\tAlt+F4")
        menu_bar.Append(dosya_menu, "D&osya")

        duzen_menu = wx.Menu()
        duzen_menu.Append(self.id_tumunu, "Tümünü &İşaretle\tAlt+A")
        duzen_menu.Append(self.id_kaldir, "İşaretleri &Kaldır\tAlt+D")
        duzen_menu.AppendSeparator()
        duzen_menu.Append(self.id_arsiv, "A&rşive Gönder\tAlt+R")
        duzen_menu.Append(self.id_sil, "&Sil\tAlt+S")
        duzen_menu.AppendSeparator()
        duzen_menu.Append(self.id_yenile, "&Yenile\tF5")
        menu_bar.Append(duzen_menu, "Dü&zen")

        ayarlar_menu = wx.Menu()
        ayarlar_menu.Append(self.id_eposta_sayisi, "&E-Posta Sayısı...")
        menu_bar.Append(ayarlar_menu, "Ayar&lar")

        yardim_menu = wx.Menu()
        yardim_menu.Append(self.id_yardim_kilavuzu, "&Yardım Kılavuzu")
        yardim_menu.AppendSeparator()
        yardim_menu.Append(self.id_oneri_gorus, "Ö&neri ve Görüş Bildir...")
        menu_bar.Append(yardim_menu, "&Yardım")

        self.SetMenuBar(menu_bar)

    def hesap_bilgisi_var_mi(self):
        ayarlar = ayarlari_yukle()
        return bool(ayarlar.get("eposta") and ayarlar.get("sifre"))

    def hesap_bilgisi_eksik_goster(self):
        self.liste.DeleteAllItems()
        self.liste.InsertItem(0, "Hesap bilgisi bulunamadı. Alt tuşuyla Dosya menüsünden Bağlan seçeneğini kullanın.")
        try:
            self.k_kutu.Enable()
        except Exception:
            pass

    def hesap_baglan(self, event=None):
        pencere = AyarlarPenceresi(self)
        try:
            sonuc = pencere.ShowModal()
        finally:
            pencere.Destroy()
        if sonuc == wx.ID_OK and pencere_kullanilabilir_mi(self):
            self.verileri_yukle_tetikle("Gelen Kutusu yükleniyor...", kategori_adi=self.secili_kategori)

    def eposta_sayisi_ayari_ac(self, event=None):
        pencere = MesajSayisiPenceresi(self)
        try:
            sonuc = pencere.ShowModal()
        finally:
            pencere.Destroy()
        if sonuc == wx.ID_OK and pencere_kullanilabilir_mi(self) and self.hesap_bilgisi_var_mi():
            self.verileri_yukle_tetikle("E-postalar yeni sayıya göre yükleniyor...", kategori_adi=self.secili_kategori)

    def yardim_kilavuzunu_ac(self, event=None):
        yardim_belgesini_ac()

    def oneri_gorus_ac(self, event=None):
        pencere = OneriGorusPenceresi(self)
        try:
            pencere.ShowModal()
        finally:
            pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.liste.SetFocus)

    def pencereyi_kapat(self, event=None):
        if event is not None and hasattr(event, "CanVeto"):
            event.Skip()
            return
        self.Close()

    def _pencere_yok_ediliyor(self, event):
        if event.GetEventObject() is self:
            self._kapatildi = True
        event.Skip()

    def aktif_klasor(self):
        return self.klasor_haritasi.get(self.secili_kategori, "INBOX")

    def okunmadi_etiketini_kaldir(self, metin):
        metin = metin or ""
        for etiket in ("[Okunmadı] ", "Okunmadı - "):
            if metin.startswith(etiket):
                return metin[len(etiket):]
        return metin

    def mesaji_listede_okundu_yap(self, mail_id):
        hedef = str(mail_id)
        for indeks, mesaj in enumerate(self.mailler):
            if str(mesaj.get("id")) != hedef:
                continue
            mesaj["kimden"] = self.okunmadi_etiketini_kaldir(mesaj.get("kimden", ""))
            gosterim = mesaj["kimden"]
            if str(mesaj.get("id")) in self.isaretliler:
                gosterim = "[İşaretli] " + gosterim
            try:
                self.liste.SetItem(indeks, 0, gosterim)
            except Exception:
                pass
            break

    def cop_klasoru_mu(self, klasor):
        cop_klasoru = self.klasor_haritasi.get("Çöp Kutusu", VARSAYILAN_KLASOR_HARITASI["Çöp Kutusu"])
        return str(klasor) == str(cop_klasoru)

    def tum_postalar_klasoru_mu(self, klasor):
        tum_postalar = self.klasor_haritasi.get("Tüm Postalar", VARSAYILAN_KLASOR_HARITASI["Tüm Postalar"])
        return str(klasor) == str(tum_postalar)

    def taslak_klasoru_mu(self, klasor):
        taslaklar = self.klasor_haritasi.get("Taslaklar", VARSAYILAN_KLASOR_HARITASI["Taslaklar"])
        return str(klasor) == str(taslaklar) or self.secili_kategori == "Taslaklar"

    def taslak_silme_onayi_al(self):
        return gui.messageBox(
            "Bu taslağı silmek istiyor musunuz?",
            "Taslak Silme Onayı",
            wx.YES_NO | wx.ICON_WARNING,
        ) == wx.YES

    def tum_postalar_arsiv_onayi_al(self, adet):
        soru = (
            "Seçili mesaj Tüm Postalar klasöründen özel bir arşiv klasörüne taşınacaktır. "
            "Gmail'in etiket davranışı hesap ayarlarınıza göre değişebilir. Devam etmek istiyor musunuz?"
            if adet == 1
            else f"Seçili {adet} mesaj Tüm Postalar klasöründen özel bir arşiv klasörüne taşınacaktır. "
            "Gmail'in etiket davranışı hesap ayarlarınıza göre değişebilir. Devam etmek istiyor musunuz?"
        )
        return gui.messageBox(soru, "Tüm Postalar Arşivleme Uyarısı", wx.YES_NO | wx.ICON_WARNING) == wx.YES

    def silme_onayi_al(self, adet, kaynak_klasor):
        if self.cop_klasoru_mu(kaynak_klasor):
            soru = (
                "Bu mesaj çöp kutusundan kalıcı olarak silinecektir. Devam etmek istiyor musunuz?"
                if adet == 1
                else f"Seçili {adet} mesaj çöp kutusundan kalıcı olarak silinecektir. Devam etmek istiyor musunuz?"
            )
            baslik = "Kalıcı Silme Onayı"
        elif self.tum_postalar_klasoru_mu(kaynak_klasor):
            soru = (
                "Seçili mesaj Tüm Postalar klasöründen çöp kutusuna taşınacaktır. "
                "Bu işlem, Gmail hesabınızda mesajı çöp kutusuna taşıyabilir. Devam etmek istiyor musunuz?"
                if adet == 1
                else f"Seçili {adet} mesaj Tüm Postalar klasöründen çöp kutusuna taşınacaktır. "
                "Bu işlem, Gmail hesabınızda mesajları çöp kutusuna taşıyabilir. Devam etmek istiyor musunuz?"
            )
            baslik = "Tüm Postalar Silme Uyarısı"
        else:
            soru = (
                "Seçili mesajı çöp kutusuna taşımak istiyor musunuz?"
                if adet == 1
                else f"Seçili {adet} mesajı çöp kutusuna taşımak istiyor musunuz?"
            )
            baslik = "Silme Onayı"
        return gui.messageBox(soru, baslik, wx.YES_NO | wx.ICON_WARNING) == wx.YES

    def liste_odak_bilgisi_al(self):
        indeks = -1
        mail_id = None
        try:
            indeks = self.liste.GetFocusedItem()
        except Exception:
            indeks = -1
        if indeks != -1 and indeks < len(self.mailler):
            mail_id = str(self.mailler[indeks].get("id", ""))
        return mail_id, indeks

    def liste_secim_ver(self, indeks):
        if not self.mailler:
            wx.CallAfter(self.liste.SetFocus)
            return
        indeks = max(0, min(int(indeks), len(self.mailler) - 1))
        try:
            self.liste.SelectAll(False)
        except Exception:
            pass
        try:
            self.liste.Focus(indeks)
            self.liste.Select(indeks)
            self.liste.EnsureVisible(indeks)
        except Exception:
            pass
        wx.CallAfter(self.liste.SetFocus)

    def verileri_yukle_tetikle(self, liste_mesaji=None, kategori_adi=None, korunan_mail_id=None, korunan_indeks=None, sessiz=False):
        if not pencere_kullanilabilir_mi(self):
            return
        if self.yukleniyor:
            ui.message("Devam eden işleminiz tamamlandıktan sonra yeniden deneyin.")
            return

        hedef_kategori = kategori_adi or self.bekleyen_kategori or self.secili_kategori

        if korunan_mail_id is None and korunan_indeks is None and hedef_kategori == self.secili_kategori:
            korunan_mail_id, korunan_indeks = self.liste_odak_bilgisi_al()

        self._yenileme_hedef_mail_id = str(korunan_mail_id) if korunan_mail_id else None
        self._yenileme_hedef_indeks = korunan_indeks if korunan_indeks is not None and korunan_indeks != -1 else None
        self._yenileme_sessiz = bool(sessiz)

        self.secili_kategori = hedef_kategori

        if liste_mesaji and not sessiz:
            self.liste.DeleteAllItems()
            self.liste.InsertItem(0, liste_mesaji)

        self.yukleniyor = True
        try:
            self.k_kutu.Disable()
        except Exception:
            pass

        kaynak_klasor = self.klasor_haritasi.get(hedef_kategori, self.aktif_klasor())
        arka_planda_calistir(self.verileri_yukle, hedef_kategori, kaynak_klasor)

    def yeni_posta_yaz(self, event=None):
        pencere = YeniPostaPenceresi(
            self,
            taslak_kaydet_callback=lambda: self.taslak_kaydedildi(),
            taslak_klasor_adaylari=self.taslak_klasor_adaylari(),
        )
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.liste.SetFocus)

    def listeyi_yenile(self, event=None):
        ui.message("Liste yenileniyor.")
        self.verileri_yukle_tetikle("E-postalar güncelleniyor...")

    def mesaj_oku(self, event):
        indeks = event.GetIndex()
        if indeks == -1 or indeks >= len(self.mailler):
            return
        mail_id = self.mailler[indeks]["id"]
        kaynak_klasor = self.aktif_klasor()
        if self.taslak_klasoru_mu(kaynak_klasor):
            ui.message("Taslak düzenleniyor.")
        else:
            ui.message("E-posta görüntüleniyor.")
        arka_planda_calistir(self.sunucudan_icerik_indir, mail_id, kaynak_klasor)

    def sunucudan_icerik_indir(self, mail_id, kaynak_klasor):
        ayarlar = ayarlari_yukle()
        try:
            klasor = kaynak_klasor or self.aktif_klasor()
            with ImapBaglantisi(ayarlar) as imap:
                tip, _veri = imap.select(klasor, readonly=False)
                if tip != "OK":
                    raise MailHatasi("Seçili klasör açılamadı.")
                tip, veri = imap.uid("FETCH", str(mail_id), "(BODY.PEEK[])")
                if tip != "OK":
                    raise MailHatasi("Mesaj içeriği alınamadı.")
                ham_veri = ham_mesaj_verisi_al(veri)
                if not ham_veri:
                    raise MailHatasi("Mesaj içeriği boş döndü.")

                mesaj = email.message_from_bytes(ham_veri, policy=email_policy.default)
                icerik, ekler = mesaj_metni_ve_ekleri_cikar(mesaj)
                kimden = guvenli_coz(mesaj.get("From", "Bilinmiyor"))
                ad, adres = email.utils.parseaddr(kimden)
                taslak_mi = self.taslak_klasoru_mu(klasor)
                veri = {
                    "id": str(mail_id),
                    "klasor": klasor,
                    "kimden_tam": f"{ad} ({adres})" if ad and adres else (adres or kimden),
                    "kimden_adres": adres or kimden,
                    "kime": adres_basligini_duzenle(mesaj.get("To", "")),
                    "konu": guvenli_coz(mesaj.get("Subject", "Konusuz")) or "Konusuz",
                    "tarih": turkce_tarih_yap(mesaj.get("Date", "")),
                    "message_id": eposta_basligi_tek_satir_yap(mesaj.get("Message-ID", "")),
                    "references": eposta_basligi_tek_satir_yap(mesaj.get("References", "")),
                    "icerik": icerik or "",
                    "ekler": ekler,
                    "taslak_mi": taslak_mi,
                }
                if not taslak_mi:
                    imap.uid("STORE", str(mail_id), "+FLAGS.SILENT", "(\\Seen)")
            if veri.get("taslak_mi"):
                guvenli_call_after(self, self.taslak_penceresini_ac, veri)
            else:
                guvenli_call_after(self, self.mesaji_listede_okundu_yap, mail_id)
                guvenli_call_after(self, self.okuma_penceresini_ac, veri)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
        except Exception as e:
            hata_kaydet("Mesaj içeriği indirilemedi.", e)
            guvenli_call_after(self, ui.message, "Mesaj açılırken bir hata oluştu.")

    def taslak_penceresini_ac(self, veri):
        if not pencere_kullanilabilir_mi(self):
            return

        pencere = YeniPostaPenceresi(
            self,
            varsayilan_kime=veri.get("kime", ""),
            varsayilan_konu=veri.get("konu", ""),
            varsayilan_icerik=veri.get("icerik", ""),
            baslik="Engelsiz Mail - Taslak Düzenle",
            gonderildi_callback=lambda: self.taslak_gonderildi(veri.get("id"), veri.get("klasor")),
            taslak_sil_callback=lambda: self.taslak_sil_iste(veri.get("id"), veri.get("klasor")),
            taslak_kaydet_callback=lambda: self.taslak_kaydedildi(veri.get("id"), veri.get("klasor")),
            taslak_klasor_adaylari=self.taslak_klasor_adaylari(veri.get("klasor")),
            hazir_ekler=veri.get("ekler", []),
        )
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.liste.SetFocus)

    def taslak_gonderildi(self, mail_id, kaynak_klasor):
        if not mail_id:
            return False
        self.listeden_mesajlari_kaldir([mail_id])
        arka_planda_calistir(self.sunucudan_taslak_sil, [mail_id], kaynak_klasor, "Taslak kaldırıldı.")
        return True

    def taslak_kaydedildi(self, mail_id=None, kaynak_klasor=None):
        """Yeni taslak kaydedildikten sonra eski taslağı kaldırır veya Taslaklar listesini yeniler."""
        eski_taslak_var = bool(mail_id)
        if eski_taslak_var:
            self.listeden_mesajlari_kaldir([mail_id])
            arka_planda_calistir(self.sunucudan_taslak_sil, [mail_id], kaynak_klasor, "")
            return True

        if self.secili_kategori == "Taslaklar" and self.hesap_bilgisi_var_mi():
            wx.CallLater(700, self.verileri_yukle_tetikle, None, self.secili_kategori, None, None, True)
        return False

    def taslak_sil_iste(self, mail_id, kaynak_klasor):
        if not mail_id:
            ui.message("Silinecek taslak bulunamadı.")
            return False
        if not self.taslak_silme_onayi_al():
            self.liste.SetFocus()
            return False
        self.listeden_mesajlari_kaldir([mail_id])
        ui.message("Taslak siliniyor.")
        arka_planda_calistir(self.sunucudan_taslak_sil, [mail_id], kaynak_klasor, "Taslak silindi.")
        return True

    def taslak_klasor_adaylari(self, kaynak_klasor=None):
        adaylar = []

        def ekle(deger):
            deger = str(deger or "").strip()
            if deger and deger not in adaylar:
                adaylar.append(deger)

        ekle(kaynak_klasor)
        ekle(self.klasor_haritasi.get("Taslaklar"))
        ekle(VARSAYILAN_KLASOR_HARITASI.get("Taslaklar"))
        ekle('"[Gmail]/Drafts"')
        ekle('"[Google Mail]/Drafts"')
        ekle(imap_klasor_adi_hazirla("Taslaklar"))
        ekle(imap_klasor_adi_hazirla("Drafts"))
        return adaylar

    def uidleri_klasorde_ara(self, imap, uidler):
        uid_kumesi = {str(uid) for uid in uidler if str(uid or "").strip()}
        if not uid_kumesi:
            return set()
        uid_araligi = ",".join(sorted(uid_kumesi, key=lambda x: int(x) if x.isdigit() else x))
        tip, veri = imap.uid("SEARCH", "UID", uid_araligi)
        if tip != "OK":
            return set()
        bulunanlar = {str(uid) for uid in uidleri_ayristir(veri)}
        return uid_kumesi.intersection(bulunanlar)

    def sunucudan_taslak_sil(self, ids, klasor, basari_mesaji="Taslak silindi."):
        ayarlar = ayarlari_yukle()
        try:
            uidler = [str(uid) for uid in ids if str(uid or "").strip()]
            if not uidler:
                raise MailHatasi("Silinecek taslak bulunamadı.")

            silindi = False
            son_hata = ""
            with ImapBaglantisi(ayarlar) as imap:
                for aday_klasor in self.taslak_klasor_adaylari(klasor):
                    try:
                        tip, _veri = imap.select(aday_klasor, readonly=False)
                        if tip != "OK":
                            son_hata = f"Taslaklar klasörü açılamadı: {aday_klasor}"
                            continue

                        mevcut_uidler = self.uidleri_klasorde_ara(imap, uidler)
                        if not mevcut_uidler:
                            son_hata = f"Taslak UID bu klasörde bulunamadı: {aday_klasor}"
                            continue

                        uid_seti = ",".join(sorted(mevcut_uidler, key=lambda x: int(x) if x.isdigit() else x))
                        tip, _veri = imap.uid("STORE", uid_seti, "+FLAGS.SILENT", "(\\Deleted)")
                        if tip != "OK":
                            son_hata = f"Taslak silme bayrağı verilemedi: {aday_klasor}"
                            continue

                        expunge_basarili = False
                        tip, _veri = imap.uid("EXPUNGE", uid_seti)
                        if tip == "OK":
                            expunge_basarili = True
                        else:
                            tip, _veri = imap.expunge()
                            if tip == "OK":
                                expunge_basarili = True

                        if not expunge_basarili:
                            try:
                                tip, _veri = imap.close()
                                expunge_basarili = tip == "OK"
                            except Exception:
                                expunge_basarili = False

                        if not expunge_basarili:
                            son_hata = f"Taslak kalıcı olarak kaldırılamadı: {aday_klasor}"
                            continue

                        try:
                            imap.select(aday_klasor, readonly=False)
                            kalan_uidler = self.uidleri_klasorde_ara(imap, mevcut_uidler)
                        except Exception:
                            kalan_uidler = set()

                        if not kalan_uidler:
                            silindi = True
                            break

                        son_hata = f"Taslak silme sonrasında hâlâ görünüyor: {aday_klasor}"
                    except Exception as e:
                        son_hata = f"Taslak silme denemesi başarısız: {aday_klasor}"
                        hata_kaydet(son_hata, e)
                        continue

            if not silindi:
                hata_kaydet(son_hata or "Taslak silinemedi.")
                raise MailHatasi("Taslak Gmail tarafından kaldırılmadı. Liste yenileniyor.")

            if basari_mesaji:
                guvenli_call_after(self, ui.message, basari_mesaji)
            guvenli_call_after(self, self.verileri_yukle_tetikle, None, self.secili_kategori, None, None, True)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
            guvenli_call_after(self, self.verileri_yukle_tetikle, None, self.secili_kategori, None, None, True)
        except Exception as e:
            hata_kaydet("Taslak silinemedi.", e)
            guvenli_call_after(self, ui.message, "Taslak silinirken bir hata oluştu.")
            guvenli_call_after(self, self.verileri_yukle_tetikle, None, self.secili_kategori, None, None, True)

    def okuma_penceresini_ac(self, veri):
        if not pencere_kullanilabilir_mi(self):
            return
        pencere = MesajOkumaPenceresi(self, veri, self)
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            self.liste.SetFocus()
            self.verileri_yukle_tetikle(
                kategori_adi=self.secili_kategori,
                korunan_mail_id=veri.get("id"),
                sessiz=True,
            )

    def arsiv_secim_goster(self, sids, kaynak_klasor=None):
        if not sids:
            ui.message("Arşivlenecek mesaj bulunamadı.")
            return
        kaynak_klasor = kaynak_klasor or self.aktif_klasor()
        if self.tum_postalar_klasoru_mu(kaynak_klasor) and not self.tum_postalar_arsiv_onayi_al(len(sids)):
            self.liste.SetFocus()
            return
        dlg = ArsivSecimPenceresi(self, self.ozel_klasorler, self)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            secim = dlg.secilen_isim
            if secim == YENI_ARSIV_SECENEGI:
                yeni_dlg = YeniKlasorPenceresi(self)
                try:
                    if yeni_dlg.ShowModal() != wx.ID_OK:
                        return
                    hedef = yeni_dlg.klasor_adi
                    yeni_mi = True
                finally:
                    yeni_dlg.Destroy()
            else:
                hedef = secim
                yeni_mi = False

            self.listeden_mesajlari_kaldir(sids)
            ui.message(f"Mesajlar '{hedef}' klasörüne arşivleniyor.")
            arka_planda_calistir(self.sunucudan_ozel_arsivle, sids, hedef, yeni_mi, kaynak_klasor)
        finally:
            dlg.Destroy()

    def arsiv_klasoru_sil(self, klasor_adi):
        ui.message("Arşiv siliniyor.")
        arka_planda_calistir(self.sunucudan_arsiv_sil_thread, klasor_adi)

    def sunucudan_arsiv_sil_thread(self, klasor_adi):
        ayarlar = ayarlari_yukle()
        try:
            with ImapBaglantisi(ayarlar) as imap:
                hedef = self.klasor_haritasi.get(klasor_adi, imap_klasor_adi_hazirla(klasor_adi))
                tip, _veri = imap.delete(hedef)
                if tip != "OK":
                    raise MailHatasi("Arşiv klasörü silinemedi.")
            guvenli_call_after(self, ui.message, "Arşiv klasörü silindi.")
            guvenli_call_after(self, self.verileri_yukle_tetikle, "Klasörler güncelleniyor...")
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
        except Exception as e:
            hata_kaydet("Arşiv klasörü silinemedi.", e)
            guvenli_call_after(self, ui.message, "Silme işlemi sırasında bir hata oluştu.")

    def sunucudan_ozel_arsivle(self, ids, hedef_isim, yeni_mi, mevcut_klasor):
        ayarlar = ayarlari_yukle()
        try:
            if not ids:
                raise MailHatasi("Arşivlenecek mesaj bulunamadı.")
            with ImapBaglantisi(ayarlar) as imap:
                hedef = self.klasor_haritasi.get(hedef_isim, imap_klasor_adi_hazirla(hedef_isim))
                if yeni_mi:
                    imap.create(hedef)
                tip, _veri = imap.select(mevcut_klasor, readonly=False)
                if tip != "OK":
                    raise MailHatasi("Kaynak klasör açılamadı.")
                uidler = ",".join(str(uid) for uid in ids)
                tip, _veri = imap.uid("COPY", uidler, hedef)
                if tip != "OK":
                    raise MailHatasi("Mesajlar hedef klasöre kopyalanamadı.")
                imap.uid("STORE", uidler, "+FLAGS", "(\\Deleted)")
                imap.expunge()
            guvenli_call_after(self, ui.message, f"Mesajlar '{hedef_isim}' klasörüne taşındı.")
            if yeni_mi:
                guvenli_call_after(self, self.verileri_yukle_tetikle, "Klasörler güncelleniyor...")
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
            guvenli_call_after(self, self.verileri_yukle_tetikle, "Liste yenileniyor...")
        except Exception as e:
            hata_kaydet("Arşivleme işlemi başarısız oldu.", e)
            guvenli_call_after(self, ui.message, "Arşivleme sırasında bir hata oluştu.")
            guvenli_call_after(self, self.verileri_yukle_tetikle, "Liste yenileniyor...")

    def tek_mesaj_sil(self, mail_id, kaynak_klasor=None):
        kaynak_klasor = kaynak_klasor or self.aktif_klasor()
        if not self.silme_onayi_al(1, kaynak_klasor):
            return False
        self.listeden_mesajlari_kaldir([mail_id])
        ui.message("Mesaj siliniyor.")
        arka_planda_calistir(self.sunucudan_sil, [mail_id], kaynak_klasor)
        return True

    def posta_sil(self, event=None):
        secili_idler = list(self.isaretliler)
        if not secili_idler:
            indeks = self.liste.GetFocusedItem()
            if indeks != -1 and indeks < len(self.mailler):
                secili_idler.append(self.mailler[indeks]["id"])
        if not secili_idler:
            ui.message("Lütfen silmek için mesaj seçin.")
            return

        adet = len(secili_idler)
        kaynak_klasor = self.aktif_klasor()
        if not self.silme_onayi_al(adet, kaynak_klasor):
            self.liste.SetFocus()
            return

        self.listeden_mesajlari_kaldir(secili_idler)
        ui.message("Siliniyor.")
        arka_planda_calistir(self.sunucudan_sil, secili_idler, kaynak_klasor)

    def listeden_mesajlari_kaldir(self, ids):
        id_kumesi = {str(uid) for uid in ids}
        silinecek_indeksler = [i for i, mesaj in enumerate(self.mailler) if str(mesaj["id"]) in id_kumesi]
        hedef_indeks = min(silinecek_indeksler) if silinecek_indeksler else self.liste.GetFocusedItem()
        for indeks in reversed(silinecek_indeksler):
            try:
                self.liste.DeleteItem(indeks)
            except Exception:
                pass
            del self.mailler[indeks]
        self.isaretliler.difference_update(id_kumesi)
        if not self.mailler:
            self.liste.DeleteAllItems()
            self.liste.InsertItem(0, "Bu klasörde gösterilecek mesaj yok.")
            wx.CallAfter(self.liste.SetFocus)
        else:
            self.liste_secim_ver(hedef_indeks)

    def sunucudan_sil(self, ids, klasor):
        ayarlar = ayarlari_yukle()
        try:
            if not ids:
                raise MailHatasi("Silinecek mesaj bulunamadı.")
            with ImapBaglantisi(ayarlar) as imap:
                tip, _veri = imap.select(klasor, readonly=False)
                if tip != "OK":
                    raise MailHatasi("Seçili klasör açılamadı.")
                uidler = ",".join(str(uid) for uid in ids)
                cop = self.klasor_haritasi.get("Çöp Kutusu", VARSAYILAN_KLASOR_HARITASI["Çöp Kutusu"])
                if klasor == cop:
                    imap.uid("STORE", uidler, "+FLAGS", "(\\Deleted)")
                    imap.expunge()
                    mesaj = "Mesaj çöp kutusundan silindi." if len(ids) == 1 else "Mesajlar çöp kutusundan silindi."
                else:
                    tip, _veri = imap.uid("COPY", uidler, cop)
                    if tip != "OK":
                        raise MailHatasi("Mesaj çöp kutusuna kopyalanamadı.")
                    imap.uid("STORE", uidler, "+FLAGS", "(\\Deleted)")
                    imap.expunge()
                    mesaj = "Mesaj çöp kutusuna taşındı." if len(ids) == 1 else "Mesajlar çöp kutusuna taşındı."
            guvenli_call_after(self, ui.message, mesaj)
            guvenli_call_after(self, self.verileri_yukle_tetikle, None, self.secili_kategori, None, None, True)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
            guvenli_call_after(self, self.verileri_yukle_tetikle, "Liste yenileniyor...")
        except Exception as e:
            hata_kaydet("Silme işlemi başarısız oldu.", e)
            guvenli_call_after(self, ui.message, "Silme işlemi sırasında bir hata oluştu.")
            guvenli_call_after(self, self.verileri_yukle_tetikle, "Liste yenileniyor...")

    def kategori_degisti(self, event):
        if getattr(self, "klasor_secimi_programatik", False):
            event.Skip()
            return

        if self.yukleniyor:
            ui.message("Klasör yüklenirken seçim değiştirilemez.")
            event.Skip()
            return

        self.bekleyen_kategori = self.k_kutu.GetStringSelection()
        event.Skip()

    def klasor_secimine_odaklandi(self, event):
        ui.message("E-posta klasörleri. Lütfen bir klasör seçiniz.")
        event.Skip()

    def listeye_odaklandi(self, event):
        if (
            not self.yukleniyor
            and self.bekleyen_kategori
            and self.bekleyen_kategori != self.yuklu_kategori
        ):
            self.verileri_yukle_tetikle(
                f"{self.bekleyen_kategori} yükleniyor...",
                kategori_adi=self.bekleyen_kategori,
            )
        event.Skip()

    def sag_tik_menusu(self, event):
        menu = wx.Menu()
        menu.Append(self.id_tumunu, "Tümünü İşaretle\tAlt+A")
        menu.Append(self.id_kaldir, "İşaretleri Kaldır\tAlt+D")
        menu.AppendSeparator()
        menu.Append(self.id_arsiv, "Arşiv\tAlt+R")
        menu.Append(self.id_sil, "Sil\tAlt+S")
        self.liste.PopupMenu(menu)
        menu.Destroy()

    def arsive_gonder_menu(self, event=None):
        secili_idler = list(self.isaretliler)
        if not secili_idler:
            indeks = self.liste.GetFocusedItem()
            if indeks != -1 and indeks < len(self.mailler):
                secili_idler.append(self.mailler[indeks]["id"])
        if not secili_idler:
            ui.message("Lütfen arşive göndermek için mesaj seçin.")
            return
        self.arsiv_secim_goster(secili_idler)

    def tumunu_isaretle(self, event=None):
        if not self.mailler:
            ui.message("İşaretlenecek mesaj yok.")
            return
        for i, mesaj in enumerate(self.mailler):
            if mesaj["id"] not in self.isaretliler:
                self.isaretliler.add(mesaj["id"])
                self.liste.SetItem(i, 0, "[İşaretli] " + mesaj["kimden"])
        ui.message(f"{len(self.isaretliler)} mesaj işaretlendi.")

    def isaretleri_kaldir(self, event=None):
        if not self.isaretliler:
            ui.message("Kaldırılacak işaret yok.")
            return
        self.isaretliler.clear()
        for i, mesaj in enumerate(self.mailler):
            self.liste.SetItem(i, 0, mesaj["kimden"])
        ui.message("İşaretler kaldırıldı.")

    def tusa_basildi(self, event):
        tus = event.GetKeyCode()
        if tus != wx.WXK_SPACE:
            event.Skip()
            return
        indeks = self.liste.GetFocusedItem()
        if indeks == -1 or indeks >= len(self.mailler):
            ui.message("İşaretlenecek mesaj yok.")
            return
        mail_id = self.mailler[indeks]["id"]
        if mail_id in self.isaretliler:
            self.isaretliler.remove(mail_id)
            self.liste.SetItem(indeks, 0, self.mailler[indeks]["kimden"])
            ui.message("İşaret kaldırıldı.")
        else:
            self.isaretliler.add(mail_id)
            self.liste.SetItem(indeks, 0, "[İşaretli] " + self.mailler[indeks]["kimden"])
            ui.message("Mesaj işaretlendi.")

    def verileri_yukle(self, kategori_adi=None, kaynak_klasor=None):
        ayarlar = ayarlari_yukle()
        mesaj_sayisi = mesaj_sayisini_duzenle(ayarlar.get(MESAJ_SAYISI_ALANI, VARSAYILAN_MESAJ_SAYISI))
        try:
            with ImapBaglantisi(ayarlar) as imap:
                self.klasorleri_guncelle(imap)
                if kategori_adi and kategori_adi in self.klasor_haritasi:
                    aktif_klasor = self.klasor_haritasi.get(kategori_adi, kaynak_klasor or "INBOX")
                else:
                    aktif_klasor = kaynak_klasor or self.aktif_klasor()
                tip, _veri = imap.select(aktif_klasor, readonly=False)
                if tip != "OK":
                    hata_kaydet(f"Klasör açılamadı: kategori={kategori_adi}, imap={aktif_klasor}")
                    raise MailHatasi("Seçili klasör açılamadı.")
                tip, veri = imap.uid("SEARCH", "ALL")
                if tip != "OK":
                    raise MailHatasi("Mesaj listesi alınamadı.")
                uidler = uidleri_ayristir(veri)

                yeni_mailler = []
                for uid in reversed(uidler[-mesaj_sayisi:]):
                    uid_str = str(uid)
                    tip, baslik_verisi = imap.uid(
                        "FETCH",
                        uid_str,
                        "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
                    )
                    if tip != "OK":
                        continue
                    ham_baslik = ham_mesaj_verisi_al(baslik_verisi)
                    mesaj = email.message_from_bytes(ham_baslik, policy=email_policy.default)
                    kimden = guvenli_coz(mesaj.get("From", "Bilinmiyor"))
                    ad, adres = email.utils.parseaddr(kimden)
                    kimden_goster = ad or adres or kimden or "Bilinmiyor"
                    if not seen_bayragi_var_mi(baslik_verisi):
                        kimden_goster = "[Okunmadı] " + kimden_goster
                    yeni_mailler.append(
                        {
                            "id": uid_str,
                            "kimden": kimden_goster,
                            "konu": guvenli_coz(mesaj.get("Subject", "Konusuz")) or "Konusuz",
                        }
                    )

            guvenli_call_after(self, self.arayuzu_yenile, yeni_mailler)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, self.yukleme_hatali, str(e))
        except Exception as e:
            hata_kaydet("Mesaj listesi yüklenemedi.", e)
            guvenli_call_after(self, self.yukleme_hatali, "Bağlantı sorunu. Lütfen internet bağlantınızı ve Google uygulama şifrenizi kontrol edin.")

    def klasorleri_guncelle(self, imap):
        tip, veri = imap.list()
        if tip != "OK" or not veri:
            return
        yeni_ozeller = []
        yeni_harita = dict(VARSAYILAN_KLASOR_HARITASI)

        for satir in veri:
            sonuc = imap_liste_satiri_ayristir(satir)
            if not sonuc:
                continue
            bayraklar, imap_adi, gorunen_ad = sonuc
            imap_degeri = imap_tirnakli_ham_ad(imap_adi)

            if "\\SENT" in bayraklar:
                yeni_harita["Gönderilmiş Öğeler"] = imap_degeri
            elif "\\DRAFTS" in bayraklar:
                yeni_harita["Taslaklar"] = imap_degeri
            elif "\\TRASH" in bayraklar:
                yeni_harita["Çöp Kutusu"] = imap_degeri
            elif "\\JUNK" in bayraklar or "\\SPAM" in bayraklar:
                yeni_harita["Spam"] = imap_degeri
            elif "\\ALL" in bayraklar:
                yeni_harita["Tüm Postalar"] = imap_degeri
            elif imap_adi.upper() == "INBOX":
                yeni_harita["Gelen Kutusu"] = "INBOX"
            elif "\\NOSELECT" not in bayraklar and "[GMAIL]" not in imap_adi.upper():
                if gorunen_ad not in yeni_ozeller and gorunen_ad not in SISTEM_KLASORLERI:
                    yeni_ozeller.append(gorunen_ad)
                    yeni_harita[gorunen_ad] = imap_degeri

        self.ozel_klasorler = yeni_ozeller
        self.klasor_haritasi = yeni_harita
        if self.secili_kategori not in self.kategori_isimleri and self.secili_kategori not in self.ozel_klasorler:
            self.secili_kategori = "Gelen Kutusu"
            self.yuklu_kategori = self.secili_kategori
            self.bekleyen_kategori = self.secili_kategori

    def yukleme_hatali(self, mesaj):
        if not pencere_kullanilabilir_mi(self):
            return
        self.yukleniyor = False
        self._yenileme_sessiz = False
        try:
            self.k_kutu.Enable()
        except Exception:
            pass
        self.liste.DeleteAllItems()
        self.liste.InsertItem(0, "E-postalar yüklenemedi.")
        ui.message(mesaj)

    def arayuzu_yenile(self, yeni_mailler):
        if not pencere_kullanilabilir_mi(self):
            return
        self.yukleniyor = False
        try:
            self.k_kutu.Enable()
        except Exception:
            pass
        self.mailler = yeni_mailler
        self.isaretliler.clear()

        eski_secim = self.secili_kategori
        self.klasor_secimi_programatik = True
        try:
            self.k_kutu.Clear()
            tum_kategoriler = self.kategori_isimleri + self.ozel_klasorler
            for kategori in tum_kategoriler:
                self.k_kutu.Append(kategori)

            indeks = self.k_kutu.FindString(eski_secim)
            if indeks != wx.NOT_FOUND:
                self.k_kutu.SetSelection(indeks)
            else:
                self.k_kutu.SetSelection(0)
                self.secili_kategori = self.kategori_isimleri[0]
        finally:
            self.klasor_secimi_programatik = False

        self.yuklu_kategori = self.secili_kategori
        self.bekleyen_kategori = self.secili_kategori

        self.liste.DeleteAllItems()
        hedef_indeks = 0
        hedef_mail_id = self._yenileme_hedef_mail_id
        hedef_indeks_yedek = self._yenileme_hedef_indeks
        sessiz_yenileme = bool(getattr(self, "_yenileme_sessiz", False))
        self._yenileme_hedef_mail_id = None
        self._yenileme_hedef_indeks = None
        self._yenileme_sessiz = False

        if not self.mailler:
            self.liste.InsertItem(0, "Bu klasörde gösterilecek mesaj yok.")
            wx.CallAfter(self.liste.SetFocus)
        else:
            for i, mesaj in enumerate(self.mailler):
                self.liste.InsertItem(i, mesaj["kimden"])
                self.liste.SetItem(i, 1, mesaj["konu"])
                if hedef_mail_id and str(mesaj.get("id")) == str(hedef_mail_id):
                    hedef_indeks = i

            if hedef_mail_id and not any(str(mesaj.get("id")) == str(hedef_mail_id) for mesaj in self.mailler):
                if hedef_indeks_yedek is not None:
                    hedef_indeks = hedef_indeks_yedek
            elif not hedef_mail_id and hedef_indeks_yedek is not None:
                hedef_indeks = hedef_indeks_yedek

            self.liste_secim_ver(hedef_indeks)

        if self.ilk_yukleme:
            self.ilk_yukleme = False

        if not sessiz_yenileme:
            ui.message(f"{self.secili_kategori} klasörü hazır. {len(self.mailler)} mesaj listelendi.")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Engelsiz Mail"

    def __init__(self):
        super().__init__()
        self.tools_menu = gui.mainFrame.sysTrayIcon.toolsMenu
        self.gelen_penceresi = None

        self.main_item = self.tools_menu.Append(wx.ID_ANY, "&Engelsiz Mail")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.ac_gelen, self.main_item)

    def terminate(self):
        try:
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.main_item.GetId())
            try:
                self.tools_menu.Remove(self.main_item)
            except Exception:
                self.tools_menu.Remove(self.main_item.GetId())
            if pencere_kullanilabilir_mi(getattr(self, "gelen_penceresi", None)):
                self.gelen_penceresi.Close()
        except Exception as e:
            hata_kaydet("Menü öğesi kaldırılırken hata oluştu.", e)
        super().terminate()

    def ac_gelen(self, event):
        self.pencereyi_baslat(menuden_geldi=True)

    def script_gelen_ac(self, gesture):
        """Engelsiz Mail penceresini açar."""
        self.pencereyi_baslat(menuden_geldi=False)

    def _gelen_penceresi_kapandi(self, event):
        if event.GetEventObject() is self.gelen_penceresi:
            self.gelen_penceresi = None
        event.Skip()

    def pencereyi_one_getir(self, pencere):
        try:
            if pencere.IsIconized():
                pencere.Iconize(False)
            pencere.Raise()
            pencere.SetFocus()
        except Exception as e:
            hata_kaydet("Açık pencere öne getirilemedi.", e)

    def pencereyi_baslat(self, menuden_geldi=False):
        def ac():
            if pencere_kullanilabilir_mi(getattr(self, "gelen_penceresi", None)):
                ui.message("Engelsiz Mail penceresi zaten açık.")
                self.pencereyi_one_getir(self.gelen_penceresi)
                return

            pencere = GelenKutusuPenceresi(gui.mainFrame)
            self.gelen_penceresi = pencere
            pencere.Bind(wx.EVT_WINDOW_DESTROY, self._gelen_penceresi_kapandi)
            pencere.Show()
            pencere.Raise()

            if pencere.hesap_bilgisi_var_mi():
                wx.CallLater(
                    1000,
                    bildirim_soyle,
                    "E-postalarınız yükleniyor. Lütfen bekleyiniz."
                )
        wx.CallAfter(ac)

    __gestures = {"kb:nvda+shift+m": "gelen_ac"}
