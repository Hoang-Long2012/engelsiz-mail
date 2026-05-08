# -*- coding: utf-8 -*-
# Engelsiz Mail
# Telif Hakkı (C) 2026 Mehmet Aykurt

import base64
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
LISTELENECEK_MESAJ_SAYISI = 50
YENI_ARSIV_SECENEGI = "-- Yeni Bir Arşiv Klasörü Oluştur --"
HESAP_BILGISI_EKSIK_UYARISI = (
    "Lütfen önce Google Hesabına Bağlan seçeneğine girerek "
    "hesap bilgilerinizi kaydedin."
)
MENU_BILDIRIM_GECIKMESI_MS = 450

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


def ayarlari_yukle():
    ayarlar = guvenli_json_oku(AYARLAR_DOSYASI, {"eposta": "", "sifre": ""})
    return {
        "eposta": str(ayarlar.get("eposta", "")).strip(),
        "sifre": str(ayarlar.get("sifre", "")).strip().replace(" ", ""),
    }


def ayarlari_kaydet(eposta, sifre):
    return guvenli_json_yaz(
        AYARLAR_DOSYASI,
        {"eposta": eposta.strip(), "sifre": sifre.strip().replace(" ", "")},
    )


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
            if isinstance(baslik, bytes) and b"\\Seen" in baslik:
                return True
            if isinstance(baslik, str) and "\\Seen" in baslik:
                return True
    except Exception:
        pass
    return False


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
        self.SetSize((650, 260))
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
                "Gmail bağlantısı kuruldu. Hesap bilgileriniz, NVDA yapılandırma klasörüne kaydedildi.",
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


class YeniPostaPenceresi(wx.Dialog):
    def __init__(self, parent, varsayilan_kime="", varsayilan_konu="", varsayilan_icerik=""):
        super().__init__(parent, title="Engelsiz Mail - Posta Yaz")
        self.ek_dosyalar = []
        self._kapatildi = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._pencere_yok_ediliyor)

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

        kapat_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(kapat_btn, 0, wx.ALL, 5)

        self.ana_duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(self.ana_duzen)
        self.SetSize((760, 650))
        self.CenterOnParent()

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
                for yol in dlg.GetPaths():
                    if yol not in self.ek_dosyalar:
                        self.ek_dosyalar.append(yol)
                        self.liste_ekler.Append(os.path.basename(yol))
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
        del self.ek_dosyalar[secili_indeks]
        self.liste_ekler.Delete(secili_indeks)
        ui.message(f"Ek kaldırıldı: {silinen_isim}")
        if self.liste_ekler.GetCount() > 0:
            self.liste_ekler.SetSelection(min(secili_indeks, self.liste_ekler.GetCount() - 1))
        self.liste_ekler.SetFocus()

    def alanlari_etkinlestir(self, etkin=True):
        denetimler = (
            self.txt_kime,
            self.txt_konu,
            self.txt_icerik,
            self.gonder_btn,
            self.ek_ekle_btn,
            self.ek_kaldir_btn,
            self.liste_ekler,
        )
        for denetim in denetimler:
            try:
                denetim.Enable(etkin)
            except Exception:
                pass

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
        ui.message("E-posta hazırlanıyor ve gönderiliyor.")
        self.alanlari_etkinlestir(False)
        arka_planda_calistir(self.arka_planda_gonder, kime, konu, icerik, alicilar, list(self.ek_dosyalar))

    def arka_planda_gonder(self, kime, konu, icerik, alicilar, ek_dosyalar):
        ayarlar = ayarlari_yukle()
        try:
            if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
                raise MailHatasi("Hesap bilgileri eksik.")

            mesaj = EmailMessage(policy=SMTP)
            mesaj["From"] = ayarlar["eposta"]
            mesaj["To"] = ", ".join(alicilar)
            mesaj["Subject"] = konu or "Konusuz"
            mesaj.set_content(icerik or "")

            for dosya_yolu in ek_dosyalar:
                if not os.path.isfile(dosya_yolu):
                    raise MailHatasi(f"Ek dosya bulunamadı: {os.path.basename(dosya_yolu)}")
                ctype, encoding = mimetypes.guess_type(dosya_yolu)
                if ctype is None or encoding is not None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                with open(dosya_yolu, "rb") as dosya:
                    mesaj.add_attachment(
                        dosya.read(),
                        maintype=maintype,
                        subtype=subtype,
                        filename=os.path.basename(dosya_yolu),
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

        kapat_btn = wx.Button(self, wx.ID_CANCEL, label="&Kapat")
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
        pencere = YeniPostaPenceresi(self, varsayilan_kime=kime, varsayilan_konu=konu, varsayilan_icerik=icerik)
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            wx.CallAfter(self.txt_icerik.SetFocus)

    def mesaji_ilet(self, event):
        konu = self.mesaj_verisi.get("konu", "")
        if not konu.lower().startswith("fwd:"):
            konu = "Fwd: " + konu
        icerik = f"\n\n\n--- İletilen Mesaj ---\n{self.mesaj_verisi.get('icerik', '')}"
        pencere = YeniPostaPenceresi(self, varsayilan_kime="", varsayilan_konu=konu, varsayilan_icerik=icerik)
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


class GelenKutusuPenceresi(wx.Dialog):
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
        self._kapatildi = False
        self.Bind(wx.EVT_WINDOW_DESTROY, self._pencere_yok_ediliyor)

        self.id_yeni = wx.NewId()
        self.id_tumunu = wx.NewId()
        self.id_kaldir = wx.NewId()
        self.id_arsiv = wx.NewId()
        self.id_sil = wx.NewId()
        self.id_yenile = wx.NewId()

        self.Bind(wx.EVT_MENU, self.yeni_posta_yaz, id=self.id_yeni)
        self.Bind(wx.EVT_MENU, self.tumunu_isaretle, id=self.id_tumunu)
        self.Bind(wx.EVT_MENU, self.isaretleri_kaldir, id=self.id_kaldir)
        self.Bind(wx.EVT_MENU, self.arsive_gonder_menu, id=self.id_arsiv)
        self.Bind(wx.EVT_MENU, self.posta_sil, id=self.id_sil)
        self.Bind(wx.EVT_MENU, self.listeyi_yenile, id=self.id_yenile)

        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [
                    (wx.ACCEL_ALT, ord("N"), self.id_yeni),
                    (wx.ACCEL_ALT, ord("A"), self.id_tumunu),
                    (wx.ACCEL_ALT, ord("D"), self.id_kaldir),
                    (wx.ACCEL_ALT, ord("R"), self.id_arsiv),
                    (wx.ACCEL_ALT, ord("S"), self.id_sil),
                    (wx.ACCEL_NORMAL, wx.WXK_F5, self.id_yenile),
                ]
            )
        )

        self.ana_duzen = wx.BoxSizer(wx.VERTICAL)
        ust = wx.BoxSizer(wx.HORIZONTAL)
        ust.Add(wx.StaticText(self, label="E-posta klasörleri:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.k_kutu = wx.Choice(self, choices=self.kategori_isimleri)
        self.k_kutu.SetName("E-posta klasörleri")
        self.k_kutu.SetSelection(0)
        self.k_kutu.Bind(wx.EVT_CHOICE, self.kategori_degisti)
        self.k_kutu.Bind(wx.EVT_SET_FOCUS, self.klasor_secimine_odaklandi)
        ust.Add(self.k_kutu, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(ust, 0, wx.EXPAND)

        self.liste = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.liste.InsertColumn(0, "Kimden", width=260)
        self.liste.InsertColumn(1, "Konu", width=430)
        self.liste.InsertItem(0, "E-postalarınız yükleniyor...")
        self.liste.Bind(wx.EVT_SET_FOCUS, self.listeye_odaklandi)
        self.liste.Bind(wx.EVT_KEY_DOWN, self.tusa_basildi)
        self.liste.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.mesaj_oku)
        self.liste.Bind(wx.EVT_CONTEXT_MENU, self.sag_tik_menusu)
        self.ana_duzen.Add(self.liste, 1, wx.ALL | wx.EXPAND, 5)

        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)

        yeni_btn = wx.Button(self, label="Yeni posta yaz (Alt+N)")
        yeni_btn.Bind(wx.EVT_BUTTON, self.yeni_posta_yaz)
        btn_duzen.Add(yeni_btn, 0, wx.ALL, 5)

        tumunu_btn = wx.Button(self, label="Tümünü işaretle (Alt+A)")
        tumunu_btn.Bind(wx.EVT_BUTTON, self.tumunu_isaretle)
        btn_duzen.Add(tumunu_btn, 0, wx.ALL, 5)

        kaldir_btn = wx.Button(self, label="İşaretleri kaldır (Alt+D)")
        kaldir_btn.Bind(wx.EVT_BUTTON, self.isaretleri_kaldir)
        btn_duzen.Add(kaldir_btn, 0, wx.ALL, 5)

        arsiv_btn = wx.Button(self, label="Arşive gönder (Alt+R)")
        arsiv_btn.Bind(wx.EVT_BUTTON, self.arsive_gonder_menu)
        btn_duzen.Add(arsiv_btn, 0, wx.ALL, 5)

        sil_btn = wx.Button(self, label="Sil (Alt+S)")
        sil_btn.Bind(wx.EVT_BUTTON, self.posta_sil)
        btn_duzen.Add(sil_btn, 0, wx.ALL, 5)

        yenile_btn = wx.Button(self, label="Yenile (F5)")
        yenile_btn.Bind(wx.EVT_BUTTON, self.listeyi_yenile)
        btn_duzen.Add(yenile_btn, 0, wx.ALL, 5)

        kapat_btn = wx.Button(self, wx.ID_CANCEL, label="&Kapat")
        btn_duzen.Add(kapat_btn, 0, wx.ALL, 5)
        self.ana_duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 5)

        self.SetSizer(self.ana_duzen)
        self.SetSize((1050, 590))
        self.CenterOnParent()
        self.verileri_yukle_tetikle("Gelen Kutusu yükleniyor...", kategori_adi=self.secili_kategori)
        wx.CallAfter(self.k_kutu.SetFocus)

    def _pencere_yok_ediliyor(self, event):
        if event.GetEventObject() is self:
            self._kapatildi = True
        event.Skip()

    def aktif_klasor(self):
        return self.klasor_haritasi.get(self.secili_kategori, "INBOX")

    def cop_klasoru_mu(self, klasor):
        cop_klasoru = self.klasor_haritasi.get("Çöp Kutusu", VARSAYILAN_KLASOR_HARITASI["Çöp Kutusu"])
        return str(klasor) == str(cop_klasoru)

    def tum_postalar_klasoru_mu(self, klasor):
        tum_postalar = self.klasor_haritasi.get("Tüm Postalar", VARSAYILAN_KLASOR_HARITASI["Tüm Postalar"])
        return str(klasor) == str(tum_postalar)

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

    def verileri_yukle_tetikle(self, liste_mesaji=None, kategori_adi=None):
        if not pencere_kullanilabilir_mi(self):
            return
        if self.yukleniyor:
            ui.message("Devam eden yükleme işlemi tamamlandıktan sonra yeniden deneyin.")
            return

        hedef_kategori = kategori_adi or self.bekleyen_kategori or self.secili_kategori
        self.secili_kategori = hedef_kategori

        if liste_mesaji:
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
        pencere = YeniPostaPenceresi(self)
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
                veri = {
                    "id": str(mail_id),
                    "klasor": klasor,
                    "kimden_tam": f"{ad} ({adres})" if ad and adres else (adres or kimden),
                    "kimden_adres": adres or kimden,
                    "konu": guvenli_coz(mesaj.get("Subject", "Konusuz")) or "Konusuz",
                    "tarih": turkce_tarih_yap(mesaj.get("Date", "")),
                    "icerik": icerik or "Metin bulunamadı.",
                    "ekler": ekler,
                }
                imap.uid("STORE", str(mail_id), "+FLAGS", "(\\Seen)")
            guvenli_call_after(self, self.okuma_penceresini_ac, veri)
        except MailHatasi as e:
            hata_kaydet(str(e))
            guvenli_call_after(self, ui.message, str(e))
        except Exception as e:
            hata_kaydet("Mesaj içeriği indirilemedi.", e)
            guvenli_call_after(self, ui.message, "Mesaj açılırken bir hata oluştu.")

    def okuma_penceresini_ac(self, veri):
        if not pencere_kullanilabilir_mi(self):
            return
        pencere = MesajOkumaPenceresi(self, veri, self)
        pencere.ShowModal()
        pencere.Destroy()
        if pencere_kullanilabilir_mi(self):
            self.liste.SetFocus()

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
        menu.Append(self.id_yeni, "Yeni Posta Yaz\tAlt+N")
        menu.AppendSeparator()
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
                for uid in reversed(uidler[-LISTELENECEK_MESAJ_SAYISI:]):
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
        if not self.mailler:
            self.liste.InsertItem(0, "Bu klasörde gösterilecek mesaj yok.")
        else:
            for i, mesaj in enumerate(self.mailler):
                self.liste.InsertItem(i, mesaj["kimden"])
                self.liste.SetItem(i, 1, mesaj["konu"])
            try:
                if wx.Window.FindFocus() == self.liste:
                    self.liste.Focus(0)
                    self.liste.Select(0)
            except Exception:
                pass

        if self.ilk_yukleme:
            self.ilk_yukleme = False
            wx.CallAfter(self.k_kutu.SetFocus)

        ui.message(f"{self.secili_kategori} klasörü hazır. {len(self.mailler)} mesaj listelendi.")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self.tools_menu = gui.mainFrame.sysTrayIcon.toolsMenu
        self.mail_menu = wx.Menu()
        self.gelen_penceresi = None

        self.item_ayarlar = self.mail_menu.Append(wx.ID_ANY, "Google Hesabına &Bağlan")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.ayarlari_ac, self.item_ayarlar)

        self.mail_menu.AppendSeparator()

        self.item_gelen = self.mail_menu.Append(wx.ID_ANY, "&Engelsiz Mail\tCtrl+Shift+M")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.ac_gelen, self.item_gelen)

        self.mail_menu.AppendSeparator()

        self.item_yardim = self.mail_menu.Append(wx.ID_ANY, "&Yardım Belgesi")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.yardimi_ac, self.item_yardim)

        self.main_item = self.tools_menu.AppendSubMenu(self.mail_menu, "Engelsiz Mail")

    def terminate(self):
        try:
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_ayarlar.GetId())
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_gelen.GetId())
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_yardim.GetId())
            self.tools_menu.Remove(self.main_item)
            if pencere_kullanilabilir_mi(getattr(self, "gelen_penceresi", None)):
                self.gelen_penceresi.Close()
        except Exception as e:
            hata_kaydet("Menü öğeleri kaldırılırken hata oluştu.", e)
        super().terminate()

    def ayarlari_ac(self, event):
        def ac():
            pencere = AyarlarPenceresi(gui.mainFrame)
            pencere.ShowModal()
            pencere.Destroy()
        wx.CallAfter(ac)

    def ac_gelen(self, event):
        self.pencereyi_baslat(menuden_geldi=True)

    def script_gelen_ac(self, gesture):
        """Engelsiz Mail gelen kutusunu açar."""
        self.pencereyi_baslat(menuden_geldi=False)

    def yardimi_ac(self, event):
        yardim_belgesini_ac()

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

            ayarlar = ayarlari_yukle()
            if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
                gecikme = MENU_BILDIRIM_GECIKMESI_MS if menuden_geldi else 0
                bildirim_soyle(HESAP_BILGISI_EKSIK_UYARISI, gecikme)
                return

            pencere = GelenKutusuPenceresi(gui.mainFrame)
            self.gelen_penceresi = pencere
            try:
                pencere.ShowModal()
            finally:
                self.gelen_penceresi = None
                pencere.Destroy()
        wx.CallAfter(ac)

    __gestures = {"kb:control+shift+m": "gelen_ac"}
