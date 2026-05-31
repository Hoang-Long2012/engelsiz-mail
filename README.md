# Engelsiz Mail

**Engelsiz Mail**, NVDA ekran okuyucusu için geliştirilmiş, Gmail hesabı üzerinden e-posta okuma ve gönderme işlemlerini sade, erişilebilir ve klavye odaklı bir arayüzle sunan bir NVDA eklentisidir.

Eklenti; görme engelli kullanıcıların karmaşık posta istemcilerine ihtiyaç duymadan, NVDA içinden hızlı biçimde e-posta okumasını, yanıtlamasını, iletmesini, taslak oluşturmasını ve dosya ekiyle posta göndermesini amaçlar.

## Öne çıkan özellikler

- Gmail hesabı ile IMAP ve SMTP üzerinden çalışma.
- Google uygulama şifresiyle güvenli bağlantı.
- Uygulama şifresini Windows DPAPI ile yerel kullanıcı hesabına bağlı şifreli saklama.
- Gelen kutusu, gönderilmiş öğeler, taslaklar, çöp kutusu, spam ve diğer Gmail klasörlerini listeleme.
- E-postaları okuma, yanıtlama, iletme, silme ve arşivleme.
- Ekli dosya gönderme ve gelen ekleri kaydetme.
- Taslak oluşturma, taslak düzenleme, taslak gönderme, taslak silme ve taslaklara kaydetme.
- Listelenecek e-posta sayısını kullanıcı tarafından belirleme.
- NVDA ile uyumlu menü tabanlı ana pencere.
- Yardım menüsünden öneri ve görüş bildirme.

## Menü yapısı

Engelsiz Mail, klasik düğme yığınları yerine program benzeri bir menü yapısıyla çalışır. Ana pencere açıkken `Alt` tuşuna basılarak menülere ulaşılabilir.

Bu yapı, NVDA eklentilerinde daha düzenli, genişletilebilir ve masaüstü uygulamasına yakın arayüzlerin kullanılabileceğini gösteren önemli bir adımdır.

Menüler şu şekildedir:

```text
Dosya
Düzen
Ayarlar
Yardım
```

### Dosya menüsü

```text
Bağlan...
Yeni Posta Yaz
Çıkış
```

### Düzen menüsü

```text
Tümünü İşaretle
İşaretleri Kaldır
Arşive Gönder
Sil
Yenile
```

### Ayarlar menüsü

```text
E-Posta Sayısı...
```

### Yardım menüsü

```text
Yardım Kılavuzu
Öneri ve Görüş Bildir...
```

## Kısayollar

| Kısayol | İşlev |
|---|---|
| `Ctrl+Shift+M` | Engelsiz Mail ana penceresini açar. |
| `Alt` | Ana pencere menüsünü açar. |
| `Alt+N` | Yeni posta yazma penceresini açar. |
| `Alt+A` | Listedeki tüm e-postaları işaretler. |
| `Alt+D` | Listedeki işaretleri kaldırır. |
| `Alt+R` | Seçili veya işaretli e-postaları arşive gönderir. |
| `Alt+S` | Seçili veya işaretli e-postaları siler. |
| `F5` | Listeyi elle yeniler. |
| `Enter` | Seçili e-postayı açar. |
| `Boşluk` | Seçili e-postayı işaretler veya işaretini kaldırır. |
| `Shift+F10` | Mesaj listesi içerik menüsünü açar. |
| `Esc` | Mesaj veya yazma penceresini kapatır; gerekiyorsa taslak kaydetme sorusu sorar. |
| `Alt+F4` | Engelsiz Mail ana penceresini kapatır. |

## Gmail hesabına bağlanma

Engelsiz Mail, Gmail hesabına bağlanmak için Google uygulama şifresi kullanır. Bu nedenle Google hesabınızda iki adımlı doğrulamanın açık olması ve bu eklenti için bir uygulama şifresi oluşturulması gerekir.

Ayrıntılı bağlantı, iki adımlı doğrulama ve uygulama şifresi oluşturma adımları için eklenti içindeki yardım kılavuzuna bakınız:

```text
Engelsiz Mail
Alt
Yardım
Yardım Kılavuzu
```

## Taslak yönetimi

Engelsiz Mail ile yeni bir e-posta yazarken iletiyi doğrudan taslaklara kaydedebilirsiniz.

Taslaklar klasöründeki bir ileti açıldığında normal okuma penceresi yerine düzenlenebilir taslak penceresi açılır. Bu pencereden taslak düzenlenebilir, gönderilebilir, silinebilir veya yeniden taslaklara kaydedilebilir.

`Esc` tuşuyla çıkarken yazılmış fakat gönderilmemiş bir içerik varsa eklenti, değişikliklerin taslaklara kaydedilip kaydedilmeyeceğini sorar.

## Güvenlik ve gizlilik

Engelsiz Mail, e-posta hesabınıza erişmek için kullandığınız uygulama şifresini düz metin olarak saklamaz. Şifre, Windows DPAPI yöntemiyle yerel kullanıcı hesabınıza bağlı olarak şifrelenir.

Eklenti, posta işlemleri dışında kullanıcı verisini haricî bir sunucuya göndermez. Öneri ve görüş bildirme özelliği kullanıldığında, kullanıcı tarafından yazılan bilgiler kullanıcının bağlı Gmail hesabı üzerinden geliştiriciye e-posta olarak gönderilir.

## Kurulum

1. GitHub Releases bölümünden `.nvda-addon` dosyasını indirin.
2. Dosyayı çalıştırın.
3. NVDA kurulum onayını verin.
4. NVDA yeniden başlatıldığında eklenti kullanılabilir olur.

Eklenti şu yollardan açılabilir:

```text
Ctrl+Shift+M
```

veya:

```text
NVDA menüsü
Araçlar
Engelsiz Mail
```

## Belgeler

Ayrıntılı kullanım kılavuzu eklenti içinde şu dosyada yer alır:

```text
doc/tr/readme.html
```

Eklenti içinden erişim:

```text
Yardım
Yardım Kılavuzu
```

## Lisans

Bu eklenti GNU Genel Kamu Lisansı Sürüm 2 kapsamında özgür yazılım olarak yayımlanmıştır.

Lisans metni için `LICENSE` dosyasına bakınız.

## Geliştirici

```text
Geliştirici: Mehmet Aykurt
E-posta: m.aykurt38@gmail.com
GitHub: https://github.com/MehmetAykurt/engelsiz-mail
```

## Not

Bu README dosyası GitHub sayfası için özet tanıtım ve kullanım bilgisi sağlar. Ayrıntılı ve ekran okuyucu odaklı açıklamalar için eklenti içindeki `doc/tr/readme.html` yardım kılavuzu esas alınmalıdır.
