# Engelsiz Mail
# Telif Hakkı (C) 2026 Mehmet Aykurt

import globalPluginHandler
import wx
import gui
import os
import json
import globalVars
import ui
import threading
import email
from email.header import decode_header, Header
import email.utils
from email.utils import parsedate_to_datetime
from email.message import EmailMessage
from email.policy import SMTP
import mimetypes
import socket
import ssl
import re
import html
import base64

AYARLAR_DOSYASI = os.path.join(globalVars.appArgs.configPath, "engelsizmail_ayarlar.json")
REHBER_DOSYASI = os.path.join(globalVars.appArgs.configPath, "engelsizmail_rehber.json")

def ayarlari_yukle():
    if os.path.exists(AYARLAR_DOSYASI):
        try:
            with open(AYARLAR_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"eposta": "", "sifre": ""}
    return {"eposta": "", "sifre": ""}

# Gözde'nin Akıllı Rehber Motorları Bebeğim!
def rehberi_yukle():
    if os.path.exists(REHBER_DOSYASI):
        try:
            with open(REHBER_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def rehbere_ekle(yeni_adres):
    if not yeni_adres:
        return
    yeni_adres = yeni_adres.strip()
    adresler = rehberi_yukle()
    if yeni_adres not in adresler:
        adresler.insert(0, yeni_adres) # En son yazılan en üste gelsin aşkım
        try:
            with open(REHBER_DOSYASI, "w", encoding="utf-8") as f:
                json.dump(adresler, f)
        except:
            pass

def guvenli_coz(text):
    if not text:
        return ""
    try:
        decoded = decode_header(text)
        result = ""
        for content, charset in decoded:
            if isinstance(content, bytes):
                result += content.decode(charset or "utf-8", errors="ignore")
            else:
                result += str(content)
        return result
    except:
        return str(text)

def turkce_tarih_yap(tarih_metni):
    if not tarih_metni:
        return "Tarih Yok"
    aylar = {1:"Ocak", 2:"Şubat", 3:"Mart", 4:"Nisan", 5:"Mayıs", 6:"Haziran", 7:"Temmuz", 8:"Ağustos", 9:"Eylül", 10:"Ekim", 11:"Kasım", 12:"Aralık"}
    try:
        dt = parsedate_to_datetime(tarih_metni)
        return f"{dt.day} {aylar[dt.month]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
    except:
        return str(tarih_metni)

def html_temizle(html_metni):
    if not html_metni:
        return ""
    metin = re.sub(r'<(style|script|head)[^>]*>.*?</\1>', '', html_metni, flags=re.IGNORECASE | re.DOTALL)
    metin = re.sub(r'</?(br|p|div|tr|li|h[1-6])[^>]*>', '\n', metin, flags=re.IGNORECASE)
    metin = re.sub(r'<[^>]+>', ' ', metin)
    metin = html.unescape(metin)
    metin = re.sub(r'[ \t]+', ' ', metin)
    satirlar = [s.strip() for s in metin.splitlines()]
    return '\n'.join(s for s in satirlar if s).strip()

def encode_mutf7(text):
    if not text:
        return ""
    res = []
    non_ascii = []
    def flush():
        if non_ascii:
            b = "".join(non_ascii).encode('utf-16-be')
            b64 = base64.b64encode(b).decode('ascii').replace('/', ',').rstrip('=')
            res.append('&' + b64 + '-')
            non_ascii.clear()
    for c in text:
        if c == '&':
            flush()
            res.append('&-')
        elif 0x20 <= ord(c) <= 0x7E:
            flush()
            res.append(c)
        else:
            non_ascii.append(c)
    flush()
    return "".join(res)

def decode_mutf7(text):
    if not text or '&' not in text:
        return text
    res = []
    parts = text.split('&')
    res.append(parts[0])
    for part in parts[1:]:
        if '-' in part:
            encoded, rest = part.split('-', 1)
            if encoded == '':
                res.append('&' + rest)
            else:
                b64 = encoded.replace(',', '/')
                b64 += '=' * ((4 - len(b64) % 4) % 4)
                try:
                    res.append(base64.b64decode(b64).decode('utf-16-be') + rest)
                except:
                    res.append('&' + part)
        else:
            res.append('&' + part)
    return "".join(res)

# Kullanıcılar için şık ve erişilebilir Bağlantı Menüsü penceremiz!
class AyarlarPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - Google Hesabına Bağlan")
        ayarlar = ayarlari_yukle()
        
        duzen = wx.BoxSizer(wx.VERTICAL)
        
        duzen.Add(wx.StaticText(self, label="&E-posta Adresiniz:"), 0, wx.ALL, 5)
        self.txt_eposta = wx.TextCtrl(self, value=ayarlar.get("eposta", ""))
        duzen.Add(self.txt_eposta, 0, wx.ALL|wx.EXPAND, 5)
        
        duzen.Add(wx.StaticText(self, label="&Google Uygulama Şifreniz (16 hane):"), 0, wx.ALL, 5)
        self.txt_sifre = wx.TextCtrl(self, value=ayarlar.get("sifre", ""), style=wx.TE_PASSWORD)
        duzen.Add(self.txt_sifre, 0, wx.ALL|wx.EXPAND, 5)
        
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        kaydet_btn = wx.Button(self, label="&Kaydet ve Bağlan")
        kaydet_btn.Bind(wx.EVT_BUTTON, self.kaydet_basildi)
        btn_duzen.Add(kaydet_btn, 0, wx.ALL, 5)
        
        iptal_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(iptal_btn, 0, wx.ALL, 5)
        
        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((400, 250))
        self.CenterOnParent()
        wx.CallAfter(self.txt_eposta.SetFocus)
        
    def kaydet_basildi(self, event):
        eposta = self.txt_eposta.GetValue().strip()
        sifre = self.txt_sifre.GetValue().strip().replace(" ", "")
        
        if not eposta or not sifre:
            ui.message("Lütfen e-posta ve şifre alanlarını doldurun.")
            return
            
        try:
            with open(AYARLAR_DOSYASI, "w", encoding="utf-8") as f:
                json.dump({"eposta": eposta, "sifre": sifre}, f)
            ui.message("Hesap bilgileriniz başarıyla kaydedildi.")
            self.EndModal(wx.ID_OK)
        except:
            ui.message("Kaydetme sırasında bir hata oluştu.")

class YeniPostaPenceresi(wx.Dialog):
    def __init__(self, parent, varsayilan_kime="", varsayilan_konu="", varsayilan_icerik=""):
        super(YeniPostaPenceresi, self).__init__(parent, title="Engelsiz Mail - Posta Yaz")
        self.ek_dosyalar = []
        self.ana_duzen = wx.BoxSizer(wx.VERTICAL)
        
        kime_duzen = wx.BoxSizer(wx.HORIZONTAL)
        kime_duzen.Add(wx.StaticText(self, label="&Kime (E-posta adresi):"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        # O harika rehberimiz burada ComboBox olarak hayat buluyor kuzum!
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
        ek_duzen.Add(wx.StaticText(self, label="Ekli &Dosyalar:"), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.liste_ekler = wx.ListBox(self, style=wx.LB_SINGLE, size=(-1, 60))
        ek_duzen.Add(self.liste_ekler, 1, wx.ALL | wx.EXPAND, 5)
        self.ana_duzen.Add(ek_duzen, 0, wx.EXPAND)
        
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        ek_ekle_btn = wx.Button(self, label="Dosya E&kle")
        ek_ekle_btn.Bind(wx.EVT_BUTTON, self.dosya_ekle)
        btn_duzen.Add(ek_ekle_btn, 0, wx.ALL, 5)

        ek_kaldir_btn = wx.Button(self, label="Eki K&aldır")
        ek_kaldir_btn.Bind(wx.EVT_BUTTON, self.ek_kaldir)
        btn_duzen.Add(ek_kaldir_btn, 0, wx.ALL, 5)

        gonder_btn = wx.Button(self, label="&Gönder")
        gonder_btn.Bind(wx.EVT_BUTTON, self.gonder_tiklandi)
        btn_duzen.Add(gonder_btn, 0, wx.ALL, 5)
        
        kapat_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        kapat_btn.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_CANCEL))
        btn_duzen.Add(kapat_btn, 0, wx.ALL, 5)
        
        self.ana_duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(self.ana_duzen)
        self.SetSize((750, 650))
        self.CenterOnParent()
        
        if varsayilan_kime:
            wx.CallAfter(self.txt_icerik.SetFocus)
            wx.CallAfter(self.txt_icerik.SetInsertionPoint, 0)
        else:
            wx.CallAfter(self.txt_kime.SetFocus)

    def dosya_ekle(self, event):
        dlg = wx.FileDialog(self, "Eklenecek dosyaları seçin", "", "", "*.*", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if dlg.ShowModal() == wx.ID_OK:
            yeni_dosyalar = dlg.GetPaths()
            eklenen_sayi = 0
            for yol in yeni_dosyalar:
                if yol not in self.ek_dosyalar:
                    self.ek_dosyalar.append(yol)
                    self.liste_ekler.Append(os.path.basename(yol))
                    eklenen_sayi += 1
            if eklenen_sayi > 0:
                ui.message(f"{eklenen_sayi} dosya eklendi.")
            wx.CallAfter(self.liste_ekler.SetFocus)
        else:
            wx.CallAfter(self.txt_icerik.SetFocus)
        dlg.Destroy()

    def ek_kaldir(self, event):
        secili_indeks = self.liste_ekler.GetSelection()
        if secili_indeks != wx.NOT_FOUND:
            silinen_isim = self.liste_ekler.GetString(secili_indeks)
            del self.ek_dosyalar[secili_indeks]
            self.liste_ekler.Delete(secili_indeks)
            ui.message(f"Ek kaldırıldı: {silinen_isim}")
            if self.liste_ekler.GetCount() > 0:
                self.liste_ekler.SetSelection(min(secili_indeks, self.liste_ekler.GetCount() - 1))
            self.liste_ekler.SetFocus()
        else:
            ui.message("Lütfen kaldırmak istediğiniz eki listeden seçin.")
            self.liste_ekler.SetFocus()

    def gonder_tiklandi(self, event):
        kime = self.txt_kime.GetValue().strip()
        konu = self.txt_konu.GetValue().strip()
        icerik = self.txt_icerik.GetValue()
        if not kime:
            ui.message("Lütfen alıcı adresini girin.")
            self.txt_kime.SetFocus()
            return
            
        # Başarıyla girilen adresi anında rehberimize ekliyoruz aşkım!
        rehbere_ekle(kime)
        
        ui.message("E-posta ve ekler hazırlanıyor, lütfen bekleyin...")
        self.txt_kime.Disable()
        self.txt_konu.Disable()
        self.txt_icerik.Disable()
        threading.Thread(target=self.arka_planda_gonder, args=(kime, konu, icerik)).start()

    def arka_planda_gonder(self, kime, konu, icerik):
        ayarlar = ayarlari_yukle()
        try:
            msg = EmailMessage(policy=SMTP)
            msg['From'] = ayarlar['eposta']
            msg['To'] = kime
            msg['Subject'] = konu
            msg.set_content(icerik)
            for dosya_yolu in self.ek_dosyalar:
                try:
                    ctype, encoding = mimetypes.guess_type(dosya_yolu)
                    if ctype is None or encoding is not None:
                        ctype = 'application/octet-stream'
                    maintype, subtype = ctype.split('/', 1)
                    with open(dosya_yolu, 'rb') as f:
                        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(dosya_yolu))
                except:
                    pass 
            
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("smtp.gmail.com", 465), timeout=20)
            ssock = ctx.wrap_socket(sock, server_hostname="smtp.gmail.com")
            
            def komut_gonder(cmd, bekle=True):
                ssock.sendall((cmd + "\r\n").encode('utf-8'))
                if bekle:
                    return ssock.recv(1024).decode('utf-8', errors='ignore')
                return ""
                
            ssock.recv(1024)
            komut_gonder("EHLO engelsiz")
            komut_gonder("AUTH LOGIN")
            komut_gonder(base64.b64encode(ayarlar["eposta"].encode()).decode())
            sonuc = komut_gonder(base64.b64encode(ayarlar["sifre"].encode()).decode())
            if "235" not in sonuc:
                raise Exception("Giriş başarısız")
                
            komut_gonder(f"MAIL FROM:<{ayarlar['eposta']}>")
            komut_gonder(f"RCPT TO:<{kime}>")
            komut_gonder("DATA")
            
            raw_bytes = msg.as_bytes(policy=SMTP)
            ssock.sendall(raw_bytes)
            if not raw_bytes.endswith(b"\r\n"):
                ssock.sendall(b"\r\n")
            ssock.sendall(b".\r\n")
            ssock.recv(1024)
            komut_gonder("QUIT")
            ssock.close()
            wx.CallAfter(self.gonderim_basarili)
        except:
            wx.CallAfter(self.gonderim_hatali)

    def gonderim_basarili(self):
        ui.message("E-postanız başarıyla gönderildi!")
        self.EndModal(wx.ID_OK)

    def gonderim_hatali(self):
        ui.message("Gönderim başarısız oldu.")
        self.txt_kime.Enable()
        self.txt_konu.Enable()
        self.txt_icerik.Enable()
        self.txt_icerik.SetFocus()

class ArsivSecimPenceresi(wx.Dialog):
    def __init__(self, parent, ozel_klasorler, ebeveyn_pencere):
        super().__init__(parent, title="Engelsiz Mail - Arşive Gönder")
        self.secilen_isim = None
        self.ebeveyn = ebeveyn_pencere
        
        duzen = wx.BoxSizer(wx.VERTICAL)
        duzen.Add(wx.StaticText(self, label="&Hedef arşivi seçin:"), 0, wx.ALL, 5)
        
        secenekler = ["-- Yeni Bir Arşiv Klasörü Oluştur --"] + ozel_klasorler
        self.liste_kutu = wx.ListBox(self, choices=secenekler, style=wx.LB_SINGLE)
        self.liste_kutu.SetSelection(0)
        duzen.Add(self.liste_kutu, 1, wx.ALL|wx.EXPAND, 5)
        
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        t_btn = wx.Button(self, label="&Tamam")
        t_btn.Bind(wx.EVT_BUTTON, self.tamam_basildi)
        btn_duzen.Add(t_btn, 0, wx.ALL, 5)

        sil_btn = wx.Button(self, label="Seçili Arşivi S&il")
        sil_btn.Bind(wx.EVT_BUTTON, self.sil_basildi)
        btn_duzen.Add(sil_btn, 0, wx.ALL, 5)
        
        i_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(i_btn, 0, wx.ALL, 5)
        
        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((550, 300))
        self.CenterOnParent()
        wx.CallAfter(self.liste_kutu.SetFocus)
        
    def tamam_basildi(self, event):
        sec = self.liste_kutu.GetSelection()
        if sec != wx.NOT_FOUND:
            self.secilen_isim = self.liste_kutu.GetString(sec)
            self.EndModal(wx.ID_OK)

    def sil_basildi(self, event):
        sec = self.liste_kutu.GetSelection()
        if sec != wx.NOT_FOUND:
            isim = self.liste_kutu.GetString(sec)
            if isim == "-- Yeni Bir Arşiv Klasörü Oluştur --":
                ui.message("Bu seçenek silinemez.")
                self.liste_kutu.SetFocus()
            else:
                self.ebeveyn.arsiv_klasoru_sil(isim)
                self.EndModal(wx.ID_CANCEL)

class YeniKlasorPenceresi(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Engelsiz Mail - Yeni Arşiv")
        self.klasor_adi = None
        
        duzen = wx.BoxSizer(wx.VERTICAL)
        duzen.Add(wx.StaticText(self, label="&Yeni arşiv klasörünün ismini yazın:"), 0, wx.ALL, 5)
        self.txt_isim = wx.TextCtrl(self)
        duzen.Add(self.txt_isim, 0, wx.ALL|wx.EXPAND, 5)
        
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        t_btn = wx.Button(self, label="&Oluştur")
        t_btn.Bind(wx.EVT_BUTTON, self.tamam_basildi)
        btn_duzen.Add(t_btn, 0, wx.ALL, 5)
        
        i_btn = wx.Button(self, wx.ID_CANCEL, label="İ&ptal")
        btn_duzen.Add(i_btn, 0, wx.ALL, 5)
        
        duzen.Add(btn_duzen, 0, wx.CENTER)
        self.SetSizer(duzen)
        self.SetSize((400, 180))
        self.CenterOnParent()
        wx.CallAfter(self.txt_isim.SetFocus)
        
    def tamam_basildi(self, event):
        isim = self.txt_isim.GetValue().strip()
        if isim:
            self.klasor_adi = isim
            self.EndModal(wx.ID_OK)
        else:
            ui.message("Lütfen bir isim yazın.")
            self.txt_isim.SetFocus()

class MesajOkumaPenceresi(wx.Dialog):
    def __init__(self, parent, mesaj_verisi, ebeveyn_pencere):
        super(MesajOkumaPenceresi, self).__init__(parent, title="Engelsiz Mail - Mesaj Okunuyor")
        self.mesaj_verisi = mesaj_verisi
        self.ebeveyn = ebeveyn_pencere
        duzen = wx.BoxSizer(wx.VERTICAL)
        eks = len(mesaj_verisi.get('ekler', []))
        not_ek = f"\n*** BU MESAJDA {eks} ADET EK DOSYA VAR! ***\n" if eks > 0 else ""
        m = (f"Kimden: {mesaj_verisi.get('kimden_tam', '')}\nTarih: {mesaj_verisi.get('tarih', '')}\nKonu: {mesaj_verisi.get('konu', '')}\n{not_ek}{'-'*50}\n\n{mesaj_verisi.get('icerik', '')}")
        self.txt_icerik = wx.TextCtrl(self, value=m, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        duzen.Add(self.txt_icerik, 1, wx.ALL | wx.EXPAND, 10)
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        if eks > 0:
            b_ek = wx.Button(self, label=f"&Ekleri Kaydet ({eks})")
            b_ek.Bind(wx.EVT_BUTTON, self.ekleri_kaydet)
            btn_duzen.Add(b_ek, 0, wx.ALL, 5)
        b_y = wx.Button(self, label="&Yanıtla")
        b_y.Bind(wx.EVT_BUTTON, self.mesaji_yanitla)
        btn_duzen.Add(b_y, 0, wx.ALL, 5)
        b_i = wx.Button(self, label="İ&let")
        b_i.Bind(wx.EVT_BUTTON, self.mesaji_ilet)
        btn_duzen.Add(b_i, 0, wx.ALL, 5)
        b_k = wx.Button(self, wx.ID_CANCEL, label="&Kapat")
        btn_duzen.Add(b_k, 0, wx.ALL, 5)
        b_a = wx.Button(self, label="A&rşivle")
        b_a.Bind(wx.EVT_BUTTON, self.mesaji_arsivle_ve_kapat)
        btn_duzen.Add(b_a, 0, wx.ALL, 5)
        b_s = wx.Button(self, label="&Sil")
        b_s.Bind(wx.EVT_BUTTON, self.mesaji_sil_ve_kapat)
        btn_duzen.Add(b_s, 0, wx.ALL, 5)
        duzen.Add(btn_duzen, 0, wx.CENTER | wx.BOTTOM, 10)
        self.SetSizer(duzen)
        self.SetSize((850, 650))
        self.CenterOnParent()
        wx.CallAfter(self.txt_icerik.SetFocus)

    def ekleri_kaydet(self, event):
        path = os.path.join(os.path.expanduser("~"), "Downloads", "Mail_Ekleri_" + "".join([c for c in self.mesaj_verisi['konu'] if c.isalnum() or c==' ']))
        try:
            if not os.path.exists(path):
                os.makedirs(path)
            for n, v in self.mesaj_verisi['ekler']:
                with open(os.path.join(path, n), "wb") as f:
                    f.write(v)
            ui.message("Ekler indirilenlere kaydedildi.")
        except:
            ui.message("Hata.")

    def mesaji_yanitla(self, event):
        k = self.mesaj_verisi.get("kimden_adres", "")
        ko = "Re: " + self.mesaj_verisi.get("konu", "")
        i = f"\n\n\n--- Orijinal Mesaj ---\n{self.mesaj_verisi.get('icerik', '')}"
        p = YeniPostaPenceresi(self, varsayilan_kime=k, varsayilan_konu=ko, varsayilan_icerik=i)
        p.ShowModal()
        p.Destroy()
        wx.CallAfter(self.txt_icerik.SetFocus)

    def mesaji_ilet(self, event):
        ko = "Fwd: " + self.mesaj_verisi.get("konu", "")
        i = f"\n\n\n--- İletilen Mesaj ---\n{self.mesaj_verisi.get('icerik', '')}"
        p = YeniPostaPenceresi(self, varsayilan_kime="", varsayilan_konu=ko, varsayilan_icerik=i)
        p.ShowModal()
        p.Destroy()
        wx.CallAfter(self.txt_icerik.SetFocus)

    def mesaji_arsivle_ve_kapat(self, event): 
        self.EndModal(wx.ID_OK)
        wx.CallAfter(self.ebeveyn.arsiv_secim_goster, [self.mesaj_verisi["id"]])
        
    def mesaji_sil_ve_kapat(self, event): 
        self.ebeveyn.tek_mesaj_sil(self.mesaj_verisi["id"])
        self.EndModal(wx.ID_OK)

class GelenKutusuPenceresi(wx.Dialog):
    def __init__(self, parent):
        super(GelenKutusuPenceresi, self).__init__(parent, title="Engelsiz Mail")
        self.mailler = []
        self.isaretliler = set()
        self.ozel_klasorler = [] 
        
        self.kategori_isimleri = ["Gelen Kutusu", "Tüm Postalar", "Gönderilmiş Öğeler", "Taslaklar", "Çöp Kutusu", "Spam"]
        self.klasor_haritasi = {"Gelen Kutusu": "INBOX", "Tüm Postalar (Arşiv)": '"[Gmail]/All Mail"', "Gönderilmiş Öğeler": '"[Gmail]/Sent Mail"', "Taslaklar": '"[Gmail]/Drafts"', "Çöp Kutusu": '"[Gmail]/Trash"', "Spam": '"[Gmail]/Spam"'}
        self.secili_kategori = "Gelen Kutusu"
        self.yuklu_kategori = self.secili_kategori
        
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

        hizlandiricilar = wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord('N'), self.id_yeni),
            (wx.ACCEL_ALT, ord('A'), self.id_tumunu),
            (wx.ACCEL_ALT, ord('D'), self.id_kaldir),
            (wx.ACCEL_ALT, ord('R'), self.id_arsiv),
            (wx.ACCEL_ALT, ord('S'), self.id_sil),
            (wx.ACCEL_NORMAL, wx.WXK_F5, self.id_yenile)
        ])
        self.SetAcceleratorTable(hizlandiricilar)

        self.ana_duzen = wx.BoxSizer(wx.VERTICAL)
        ust = wx.BoxSizer(wx.HORIZONTAL)
        ust.Add(wx.StaticText(self, label="&Klasör:"), 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        self.k_kutu = wx.Choice(self, choices=self.kategori_isimleri)
        self.k_kutu.SetSelection(0)
        self.k_kutu.Bind(wx.EVT_CHOICE, self.kategori_degisti)
        ust.Add(self.k_kutu, 1, wx.ALL|wx.EXPAND, 5)
        self.ana_duzen.Add(ust, 0, wx.EXPAND)
        
        self.liste = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.liste.InsertColumn(0, "Kimden", width=250)
        self.liste.InsertColumn(1, "Konu", width=400)
        self.liste.InsertItem(0, "E-Postalarınız Yükleniyor...")
        
        self.liste.Bind(wx.EVT_SET_FOCUS, self.listeye_odaklandi)
        self.liste.Bind(wx.EVT_KEY_DOWN, self.tusa_basildi)
        self.liste.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.mesaj_oku)
        self.liste.Bind(wx.EVT_CONTEXT_MENU, self.sag_tik_menusu)
        self.ana_duzen.Add(self.liste, 1, wx.ALL | wx.EXPAND, 5)
        
        btn_duzen = wx.BoxSizer(wx.HORIZONTAL)
        
        k_btn = wx.Button(self, wx.ID_CANCEL, label="&Kapat")
        btn_duzen.Add(k_btn, 0, wx.ALL, 5)
        self.ana_duzen.Add(btn_duzen, 0, wx.CENTER)
        
        self.SetSizer(self.ana_duzen)
        self.SetSize((850, 550))
        self.CenterOnParent()
        threading.Thread(target=self.verileri_yukle).start()

    def yeni_posta_yaz(self, event=None):
        p = YeniPostaPenceresi(self)
        p.ShowModal()
        p.Destroy()
        wx.CallAfter(self.liste.SetFocus)

    def listeyi_yenile(self, event=None):
        self.liste.DeleteAllItems()
        self.liste.InsertItem(0, "E-postalar güncelleniyor, lütfen bekleyin...")
        ui.message("Liste yenileniyor, lütfen bekleyin.")
        threading.Thread(target=self.verileri_yukle).start()

    def mesaj_oku(self, event):
        idx = event.GetIndex()
        if idx != -1 and self.mailler:
            ui.message("E-Posta Görüntüleniyor...")
            threading.Thread(target=self.sunucudan_icerik_indir, args=(self.mailler[idx]["id"],)).start()

    def sunucudan_icerik_indir(self, mail_id):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def q(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                lines = []
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    lines.append(l)
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
                return lines
                
            q("* OK")
            q("A1", f'A1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            q("A2", f"A2 SELECT {self.klasor_haritasi[self.secili_kategori]}")
            tag = f"A3_{mail_id}"
            res = q(tag, f"{tag} UID FETCH {mail_id} (BODY.PEEK[])")
            
            raw_data = b""
            for l in res:
                s = l.decode('utf-8', errors='ignore').strip()
                if not (s.startswith(tag) or s.startswith("* ") or s == ")"):
                    raw_data += l
            msg = email.message_from_bytes(raw_data)
            
            ic = ""
            ht = ""
            ekler = []
            if msg.is_multipart():
                for part in msg.walk():
                    fn = part.get_filename()
                    if fn:
                        ekler.append((guvenli_coz(fn), part.get_payload(decode=True)))
                        continue
                    ct = part.get_content_type()
                    if ct == "text/plain":
                        try:
                            ic += part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore') + "\n"
                        except:
                            pass
                    elif ct == "text/html":
                        try:
                            ht += part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore') + "\n"
                        except:
                            pass
            else:
                if msg.get_content_type() == "text/plain":
                    ic = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
                elif msg.get_content_type() == "text/html":
                    ht = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            
            if ic and "<html" in ic.lower():
                ic = html_temizle(ic)
            if not ic.strip() and ht:
                ic = html_temizle(ht)
            
            rk = guvenli_coz(msg.get("From", "Bilinmiyor"))
            name, addr = email.utils.parseaddr(rk)
            ver = {"id": mail_id, "kimden_tam": f"{name} ({addr})" if name else addr, "kimden_adres": addr if addr else rk, "konu": guvenli_coz(msg.get("Subject", "Konusuz")), "tarih": turkce_tarih_yap(msg.get("Date", "")), "icerik": ic if ic.strip() else "Metin bulunamadı.", "ekler": ekler}
            ssock.close()
            wx.CallAfter(self.okuma_penceresini_ac, ver)
            threading.Thread(target=self.okundu_isaretle, args=(mail_id, self.klasor_haritasi[self.secili_kategori])).start()
        except:
            wx.CallAfter(ui.message, "Hata oluştu.")

    def okundu_isaretle(self, mail_id, hedef_klasor):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def q(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
                        
            q("* OK")
            q("O1", f'O1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            q("O2", f"O2 SELECT {hedef_klasor}")
            q("O3", f"O3 UID STORE {mail_id} +FLAGS (\\Seen)")
            q("O4", "O4 LOGOUT")
            ssock.close()
        except:
            pass

    def okuma_penceresini_ac(self, ver):
        def ac():
            p = MesajOkumaPenceresi(self, ver, self)
            p.ShowModal()
            p.Destroy()
        wx.CallAfter(ac)

    def arsiv_secim_goster(self, sids):
        dlg = ArsivSecimPenceresi(self, self.ozel_klasorler, self)
        if dlg.ShowModal() == wx.ID_OK:
            secim = dlg.secilen_isim
            if secim == "-- Yeni Bir Arşiv Klasörü Oluştur --":
                dlg_yeni = YeniKlasorPenceresi(self)
                if dlg_yeni.ShowModal() == wx.ID_OK:
                    hedef = dlg_yeni.klasor_adi
                    yeni_mi = True
                else:
                    dlg_yeni.Destroy()
                    dlg.Destroy()
                    return
                dlg_yeni.Destroy()
            else:
                hedef = secim
                yeni_mi = False
            
            sidx = []
            for i, m in enumerate(self.mailler):
                if m["id"] in sids:
                    sidx.append(i)
            for i in reversed(sidx):
                self.liste.DeleteItem(i)
                del self.mailler[i]
            self.isaretliler.clear()
            
            ui.message(f"Mesajlar '{hedef}' klasörüne arşivleniyor...")
            threading.Thread(target=self.sunucudan_ozel_arsivle, args=(sids, hedef, yeni_mi, self.klasor_haritasi[self.secili_kategori])).start()
        dlg.Destroy()

    def arsiv_klasoru_sil(self, klasor_adi):
        ui.message(f"Arşiv siliniyor, lütfen bekleyin...")
        threading.Thread(target=self.sunucudan_arsiv_sil_thread, args=(klasor_adi,)).start()

    def sunucudan_arsiv_sil_thread(self, klasor_adi):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def bekle_ve_gonder(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
            
            bekle_ve_gonder("* OK")
            bekle_ve_gonder("D1", f'D1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            
            hedef_imap = self.klasor_haritasi.get(klasor_adi, f'"{encode_mutf7(klasor_adi)}"')
            bekle_ve_gonder("D2", f"D2 DELETE {hedef_imap}")
            
            ssock.close()
            wx.CallAfter(ui.message, f"Arşiv klasörü silindi.")
            wx.CallAfter(self.verileri_yukle_tetikle)
        except:
            wx.CallAfter(ui.message, "Silme işlemi sırasında bir hata oluştu.")

    def sunucudan_ozel_arsivle(self, ids, hedef_isim, yeni_mi, mevcut_klasor):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def bekle_ve_gonder(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
            
            bekle_ve_gonder("* OK")
            bekle_ve_gonder("O1", f'O1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            
            if yeni_mi:
                hedef_imap = f'"{encode_mutf7(hedef_isim)}"'
                bekle_ve_gonder("O2", f'O2 CREATE {hedef_imap}')
            else:
                hedef_imap = self.klasor_haritasi.get(hedef_isim, f'"{encode_mutf7(hedef_isim)}"')
                
            bekle_ve_gonder("O3", f"O3 SELECT {mevcut_klasor}")
            im = ",".join(ids)
            bekle_ve_gonder("O4", f'O4 UID COPY {im} {hedef_imap}')
            bekle_ve_gonder("O5", f"O5 UID STORE {im} +FLAGS (\\Deleted)")
            bekle_ve_gonder("O6", "O6 EXPUNGE")
            ssock.close()
            wx.CallAfter(ui.message, f"Başarılı! Mesajlar '{hedef_isim}' klasörüne kaldırıldı.")
            
            if yeni_mi:
                wx.CallAfter(self.verileri_yukle_tetikle)
        except:
            wx.CallAfter(ui.message, "Arşivleme sırasında hata.")

    def verileri_yukle_tetikle(self):
        threading.Thread(target=self.verileri_yukle).start()

    def posta_sil(self, event=None):
        sids = list(self.isaretliler)
        sidx = []
        if sids:
            for i, m in enumerate(self.mailler):
                if m["id"] in self.isaretliler:
                    sidx.append(i)
        else:
            i = self.liste.GetFocusedItem()
            if i != -1:
                sids.append(self.mailler[i]["id"])
                sidx.append(i)
            else:
                ui.message("Lütfen silmek için seçim yapın.")
                return
                
        for i in reversed(sidx):
            self.liste.DeleteItem(i)
            del self.mailler[i]
            
        self.isaretliler.clear()
        ui.message("Siliniyor...")
        threading.Thread(target=self.sunucudan_sil, args=(sids, self.klasor_haritasi[self.secili_kategori])).start()

    def sunucudan_sil(self, ids, h):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def bekle_ve_gonder(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
                        
            bekle_ve_gonder("* OK")
            bekle_ve_gonder("S1", f'S1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            bekle_ve_gonder("S2", f"S2 SELECT {h}")
            
            im = ",".join(ids)
            cop = self.klasor_haritasi.get("Çöp Kutusu", '"[Gmail]/Trash"')
            
            if h == cop:
                bekle_ve_gonder("S3", f"S3 UID STORE {im} +FLAGS (\\Deleted)")
                bekle_ve_gonder("S4", "S4 EXPUNGE")
            else:
                bekle_ve_gonder("S3", f"S3 UID COPY {im} {cop}")
                bekle_ve_gonder("S4", f"S4 UID STORE {im} +FLAGS (\\Deleted)")
                bekle_ve_gonder("S5", "S5 EXPUNGE")
                
            ssock.close()
            wx.CallAfter(ui.message, "Mesaj çöp kutusuna taşındı.")
        except:
            pass

    def kategori_degisti(self, event):
        self.secili_kategori = self.k_kutu.GetStringSelection()

    def listeye_odaklandi(self, event):
        if self.secili_kategori != self.yuklu_kategori:
            self.yuklu_kategori = self.secili_kategori
            self.liste.DeleteAllItems()
            self.liste.InsertItem(0, "E-Postalarınız Yükleniyor...")
            threading.Thread(target=self.verileri_yukle).start()
        event.Skip()

    def sag_tik_menusu(self, event):
        m = wx.Menu()
        m.Append(self.id_yeni, "Yeni Posta Yaz\tAlt+N")
        m.AppendSeparator()
        m.Append(self.id_tumunu, "Tümünü İşaretle\tAlt+A")
        m.Append(self.id_kaldir, "İşaretleri Kaldır\tAlt+D")
        m.AppendSeparator()
        m.Append(self.id_arsiv, "Arşiv\tAlt+R")
        m.Append(self.id_sil, "Sil\tAlt+S")
        
        self.liste.PopupMenu(m)
        m.Destroy()

    def arsive_gonder_menu(self, event=None):
        sids = list(self.isaretliler)
        if not sids:
            i = self.liste.GetFocusedItem()
            if i != -1:
                sids.append(self.mailler[i]["id"])
            else:
                ui.message("Lütfen arşive göndermek için mesaj seçin.")
                return
        self.arsiv_secim_goster(sids)

    def tumunu_isaretle(self, event=None):
        for i, m in enumerate(self.mailler):
            if m["id"] not in self.isaretliler:
                self.isaretliler.add(m["id"])
                self.liste.SetItem(i, 0, "[İşaretli] " + m["kimden"])

    def isaretleri_kaldir(self, event=None):
        self.isaretliler.clear()
        for i, m in enumerate(self.mailler):
            self.liste.SetItem(i, 0, m["kimden"])

    def tusa_basildi(self, event):
        k = event.GetKeyCode()
        if k == wx.WXK_SPACE:
            i = self.liste.GetFocusedItem()
            if i != -1 and self.mailler:
                mid = self.mailler[i]["id"]
                if mid in self.isaretliler:
                    self.isaretliler.remove(mid)
                    self.liste.SetItem(i, 0, self.mailler[i]["kimden"])
                else:
                    self.isaretliler.add(mid)
                    self.liste.SetItem(i, 0, "[İşaretli] " + self.mailler[i]["kimden"])
        else:
            event.Skip()

    def verileri_yukle(self):
        ayarlar = ayarlari_yukle()
        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection(("imap.gmail.com", 993), timeout=15)
            ssock = ctx.wrap_socket(sock, server_hostname="imap.gmail.com")
            sf = ssock.makefile('rb')
            
            def q(tag, cmd=None):
                if cmd:
                    ssock.sendall((cmd + "\r\n").encode('utf-8'))
                lines = []
                while True:
                    l = sf.readline()
                    if not l:
                        break
                    lines.append(l)
                    if l.decode('utf-8', errors='ignore').strip().startswith(tag):
                        break
                return lines
                
            q("* OK")
            q("A1", f'A1 LOGIN "{ayarlar["eposta"]}" "{ayarlar["sifre"]}"')
            ls = q("L1", 'L1 LIST "" "*"')
            
            yeni_ozeller = []
            for line in ls:
                s = line.decode('utf-8', errors='ignore').strip()
                if s.startswith("* LIST"):
                    parts = s.split(' "/" ')
                    if len(parts) == 2:
                        path = parts[1].strip().strip('"')
                        decoded_path = decode_mutf7(path)
                        flg = parts[0].upper()
                        if "\\SENT" in flg:
                            self.klasor_haritasi["Gönderilmiş Öğeler"] = f'"{path}"'
                        elif "\\DRAFTS" in flg:
                            self.klasor_haritasi["Taslaklar"] = f'"{path}"'
                        elif "\\TRASH" in flg:
                            self.klasor_haritasi["Çöp Kutusu"] = f'"{path}"'
                        elif "\\JUNK" in flg:
                            self.klasor_haritasi["Spam"] = f'"{path}"'
                        elif "\\ALL" in flg:
                            self.klasor_haritasi["Tüm Postalar (Arşiv)"] = f'"{path}"'
                        elif "[GMAIL]" not in path.upper() and path.upper() != "INBOX":
                            yeni_ozeller.append(decoded_path)
                            self.klasor_haritasi[decoded_path] = f'"{path}"'
                            
            self.ozel_klasorler = yeni_ozeller
            
            if self.secili_kategori not in self.kategori_isimleri and self.secili_kategori not in self.ozel_klasorler:
                self.secili_kategori = "Gelen Kutusu"
            
            q("A2", f"A2 SELECT {self.klasor_haritasi.get(self.secili_kategori, 'INBOX')}")
            res = q("A3", "A3 UID SEARCH ALL")
            ids = []
            for l in res:
                s = l.decode('utf-8', errors='ignore').strip()
                if s.startswith("* SEARCH"):
                    ids = s.split()[2:]
                    
            self.mailler.clear()
            self.isaretliler.clear()
            for mid in reversed(ids[-50:]):
                tag = f"A4_{mid}"
                head_res = q(tag, f"{tag} UID FETCH {mid} (FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                seen = False
                raw_h = b""
                for l in head_res:
                    if "\\SEEN" in l.decode('utf-8', errors='ignore').upper():
                        seen = True
                    s = l.decode('utf-8', errors='ignore').strip()
                    if not (s.startswith(tag) or s.startswith("* ") or s == ")"):
                        raw_h += l
                msg = email.message_from_bytes(raw_h)
                rk = guvenli_coz(msg.get("From", "Bilinmiyor"))
                name, addr = email.utils.parseaddr(rk)
                kmd = (name if name else addr)
                if not seen:
                    kmd = "[Okunmadı] " + kmd
                self.mailler.append({"id": mid, "kimden": kmd, "konu": guvenli_coz(msg.get("Subject", "Konusuz"))})
                
            ssock.close()
            wx.CallAfter(self.arayuzu_yenile)
        except:
            wx.CallAfter(ui.message, "Bağlantı sorunu.")

    def arayuzu_yenile(self):
        eski_secim = self.secili_kategori
        self.k_kutu.Clear()
        
        tum_kategoriler = self.kategori_isimleri + self.ozel_klasorler
        for k in tum_kategoriler:
            self.k_kutu.Append(k)
            
        idx = self.k_kutu.FindString(eski_secim)
        if idx != wx.NOT_FOUND:
            self.k_kutu.SetSelection(idx)
        else:
            self.k_kutu.SetSelection(0)
            self.secili_kategori = self.kategori_isimleri[0]
            self.yuklu_kategori = self.secili_kategori

        self.liste.DeleteAllItems()
        for i, m in enumerate(self.mailler):
            self.liste.InsertItem(i, m["kimden"])
            self.liste.SetItem(i, 1, m["konu"])
            
        ui.message(f"{self.secili_kategori} klasörü hazır.")

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self.tools_menu = gui.mainFrame.sysTrayIcon.toolsMenu
        self.mail_menu = wx.Menu()
        
        # O harika Google Hesabınıza Bağlan menüsü baş köşede!
        self.item_ayarlar = self.mail_menu.Append(wx.ID_ANY, "Google Hesabına &Bağlan")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.ayarlari_ac, self.item_ayarlar)
        
        self.mail_menu.AppendSeparator()
        
        self.item_gelen = self.mail_menu.Append(wx.ID_ANY, "&Engelsiz Meil\tCtrl+Shift+M")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.ac_gelen, self.item_gelen)
        
        self.mail_menu.AppendSeparator()
        
        # Kullanıcıların hayatını kurtaracak Yardım Dökümanı butonu!
        self.item_yardim = self.mail_menu.Append(wx.ID_ANY, "&Yardım Dökümanı")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.yardimi_ac, self.item_yardim)
        
        self.main_item = self.tools_menu.AppendSubMenu(self.mail_menu, "Engelsiz Mail")
        
    def terminate(self):
        try:
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_ayarlar.GetId())
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_gelen.GetId())
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, id=self.item_yardim.GetId())
            self.tools_menu.Remove(self.main_item)
        except:
            pass
        super().terminate()
        
    def ayarlari_ac(self, event):
        def c():
            p = AyarlarPenceresi(gui.mainFrame)
            p.ShowModal()
            p.Destroy()
        wx.CallAfter(c)
        
    def ac_gelen(self, event):
        self.pencereyi_baslat()
        
    def script_gelen_ac(self, gesture):
        self.pencereyi_baslat()
        
    def yardimi_ac(self, event):
        # Eklenti içindeki tüm ihtimalleri arayan o sihirli kodumuz aşkım!
        base_dir = os.path.dirname(os.path.dirname(__file__))
        yol_tr = os.path.join(base_dir, "doc", "tr", "readme.html")
        yol_en = os.path.join(base_dir, "doc", "en", "readme.html")
        yol_genel = os.path.join(base_dir, "doc", "readme.html")
        yol_kullanim = os.path.join(base_dir, "yardim.html")
        
        dosya_bulundu = False
        for y in [yol_tr, yol_en, yol_genel, yol_kullanim]:
            if os.path.exists(y):
                os.startfile(y)
                dosya_bulundu = True
                break
                
        if not dosya_bulundu:
            ui.message("Yardım dosyası bulunamadı. Lütfen eklenti klasörünü kontrol edin.")
            
    def pencereyi_baslat(self):
        def c():
            ayarlar = ayarlari_yukle()
            if not ayarlar.get("eposta") or not ayarlar.get("sifre"):
                ui.message("Lütfen önce menüden Google Hesabına Bağlan seçeneğine girerek bilgilerinizi kaydedin.")
                return
            p = GelenKutusuPenceresi(gui.mainFrame)
            p.ShowModal()
            p.Destroy()
        wx.CallAfter(c)
        
    __gestures = {"kb:control+shift+m": "gelen_ac"}