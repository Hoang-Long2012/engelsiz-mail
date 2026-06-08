# Engelsiz Mail

**Engelsiz Mail**, NVDA ekran okuyucusu kullanıcıları için geliştirilen erişilebilir bir Gmail e-posta eklentisidir.

Bu eklenti, görme engelli kullanıcıların e-posta okuma, yazma, yanıtlama, iletme, arşivleme, taşıma, silme, taslak yönetimi, e-posta ön izlemesi, yeni e-posta bildirimi, dosyaya kaydetme, EML dosyası açma ve bağlantı denetimi gibi temel işlemleri NVDA üzerinden daha sade ve erişilebilir biçimde yapabilmesini amaçlar.

## Bilgiler

- **Eklenti adı:** Engelsiz Mail
- **Sürüm:** 1.4.0
- **Geliştirici:** Mehmet Aykurt
- **E-posta:** m.aykurt38@gmail.com
- **Resmî web sitesi:** https://mehmetaykurt.com.tr
- **Telif hakkı:** © 2026 Mehmet Aykurt
- **Lisans:** GNU Genel Kamu Lisansı, sürüm 2.0

## Temel Özellikler

- Gmail hesabına uygulama şifresiyle bağlanma
- E-posta klasörlerini listeleme
- Gelen e-postaları okuma
- Yeni e-posta yazma
- E-postaları yanıtlama ve iletme
- Taslak oluşturma, düzenleme, gönderme ve silme
- Gönderilen E-postalar ve Taslaklar klasörlerinde alıcı, yani **Kime** bilgisini gösterme
- E-posta okuma penceresinde **Kime** bilgisini gösterme
- E-posta listesinde isteğe bağlı ön izleme okuma
- Türkçe karakter, HTML, quoted-printable ve Base64 kodlamalı ön izleme içeriklerini çözümleme
- Delete tuşu ile e-posta silme
- Silerken onay sorup sormamayı ayarlayabilme
- Yeni e-posta bildirimi
- Bildirim kontrol aralığını 5 ile 60 dakika arasında seçebilme
- Sesle ve mesajla bildirim seçenekleri
- Bildirimde gönderen adresini ve konu bilgisini okutabilme
- Varsayılan sistem sesi veya kullanıcı tanımlı WAV dosyasıyla bildirim verebilme
- E-postayı TXT veya EML biçiminde kaydetme
- Daha önce kaydedilmiş EML dosyasını açma
- E-posta eklerini kaydetme
- Arşiv klasörü oluşturma, yeniden adlandırma ve silme
- E-postaları arşive gönderme
- E-postaları Gelen Kutusu veya özel arşiv klasörlerine taşıma
- Çöp Kutusu, Spam, Taslaklar ve Tüm Postalar için açıklayıcı işlem uyarıları
- Ayrıntılı bağlantı denetimi
- Sağ tık menüsü desteği
- Yazı tipi, yazı boyutu, yazı stili, metin rengi ve arka plan rengi ayarları
- Yardım, Yenilikler, Hakkında ve Öneri-Görüş bölümleri

## Google Hesabına Bağlanma

Engelsiz Mail’i kullanabilmek için Google hesabınızda iki adımlı doğrulamanın açık olması ve bu eklenti için bir uygulama şifresi oluşturulması gerekir.

Uygulama şifresi oluşturmak için Google hesabınızda aşağıdaki sayfayı kullanabilirsiniz:

https://myaccount.google.com/apppasswords

Google tarafından verilen 16 haneli uygulama şifresi, Engelsiz Mail içindeki **Bağlan...** penceresine boşluksuz olarak yazılmalıdır.

## Not

1.3.0 sürümünde ayar dosyaları, daha düzenli bir yapı sağlamak amacıyla `engelsiz-mail` klasörü altında tutulmaya başlanmıştır.

Önceki sürümden güncelleme yapan kullanıcıların, eklentiyi ilk açtıklarında hesap bilgilerini yeniden kaydetmeleri gerekebilir.

1.4.0 sürümünde ön izleme, yeni e-posta bildirimleri, Delete tuşuyla silme, silme onayı ayarı, e-postayı TXT/EML olarak kaydetme, EML dosyası açma ve bildirim sesi seçimi gibi yeni özellikler eklenmiştir.

## Kullanım

Eklenti kurulduktan sonra Engelsiz Mail ana penceresi NVDA menüsündeki **Araçlar > Engelsiz Mail** seçeneğiyle veya tanımlı kısayolla açılabilir.

Ana pencerede klasör seçimi, e-posta listesi ve menü seçenekleri klavye ile kullanılabilir.

Temel menüler:

- **Dosya:** Yeni e-posta yazma, bağlanma, bağlantı denetimi, e-postayı kaydetme, EML dosyası açma ve çıkış işlemleri
- **Düzen:** Arşivleme, taşıma, silme, yenileme ve işaretleme işlemleri
- **Görünüm:** Yazı tipi, yazı boyutu, stil ve renk ayarları
- **Ayarlar:** Listelenecek e-posta sayısı, ön izleme, silme onayı ve bildirim ayarları
- **Yardım:** Yardım kılavuzu, yenilikler, hakkında ve öneri-görüş bölümleri

Ayrıntılı kullanım bilgileri için eklenti içindeki **Yardım Kılavuzu** bölümüne bakılabilir.

## 1.4.0 Yenilikleri

1.4.0 sürümüyle birlikte Engelsiz Mail daha kapsamlı bir erişilebilir e-posta istemcisi hâline gelmiştir.

Öne çıkan yenilikler:

- E-posta listesinde isteğe bağlı ön izleme
- Yeni e-posta bildirimi
- Bildirimlerde ses, mesaj, gönderen ve konu seçenekleri
- Varsayılan sistem sesi veya kullanıcı tanımlı WAV dosyası seçimi
- Delete tuşuyla silme
- Silerken onay sor ayarı
- Gönderilen E-postalar ve Taslaklar klasörlerinde **Kime** bilgisinin gösterilmesi
- E-postayı TXT veya EML biçiminde kaydetme
- Kaydedilmiş EML dosyasını açma

Ön izleme özelliği açık olduğunda e-posta listesi yüklenirken kısa içerik bilgisi de çözümlenir. Bu nedenle çok sayıda e-posta listelenirken işlem süresi, ön izleme kapalı duruma göre biraz daha uzun olabilir.

Bildirimler, Ayarlar menüsündeki **Bildirimler...** seçeneğinden yapılandırılır. Kontrol aralığı 5 ile 60 dakika arasında seçilebilir. Varsayılan kontrol aralığı 30 dakikadır.

## Güvenlik ve Gizlilik

Engelsiz Mail, Gmail hesabına ana Google hesap şifresiyle değil, Google uygulama şifresiyle bağlanır.

Uygulama şifresi Windows kullanıcı hesabına bağlı şifreli biçimde saklanır.

Eklenti, kullanıcı e-postalarını geliştiriciye veya üçüncü taraf bir sunucuya göndermez.

**Öneri ve Görüş Bildir** bölümü yalnızca kullanıcı formu doldurup gönderdiğinde geliştiriciye e-posta gönderir.

Bildirim ayarları ve kullanıcı tanımlı WAV dosyası yolu, yalnızca kullanıcının kendi bilgisayarında yerel ayar olarak saklanır.

Bu eklenti Google tarafından geliştirilmiş resmî bir Google ürünü değildir. Mehmet Aykurt tarafından NVDA kullanıcılarının erişilebilirlik ihtiyacına yönelik olarak geliştirilmiş bağımsız bir eklentidir.

## Bilinen Sınırlar

- Engelsiz Mail, Gmail hesabı ile IMAP ve SMTP üzerinden çalışır.
- Gmail hesabınızda IMAP erişiminin açık olması gerekebilir.
- İnternet bağlantısı yoksa veya uygulama şifresi hatalıysa e-posta listesi yüklenemez.
- Ön izleme özelliği açık olduğunda e-posta listesi yüklenirken ek içerik çözümleme yapılacağı için listeleme süresi uzayabilir.
- Bildirimler, belirlenen kontrol aralığına göre çalışır; bu nedenle yeni e-posta bildirimi anlık değil, seçilen aralığa bağlıdır.
- Kullanıcı tanımlı bildirim sesi için WAV dosyası kullanılmalıdır.
- Çok büyük ekli dosyalarda gönderme, kaydetme ve taslak işlemleri bağlantı hızına göre zaman alabilir.

## Lisans

Engelsiz Mail, GNU Genel Kamu Lisansı, sürüm 2.0 kapsamında yayımlanır.

Kaynak kod, lisans koşullarına uygun biçimde incelenebilir, değiştirilebilir ve paylaşılabilir.

Telif hakkı bildirimi, geliştirici bilgileri ve lisans koşulları korunmalıdır.

## İletişim

- **Geliştirici:** Mehmet Aykurt
- **E-posta:** m.aykurt38@gmail.com
- **Resmî web sitesi:** https://mehmetaykurt.com.tr

Öneri, görüş, hata bildirimi ve katkılarınızı paylaşabilirsiniz.
