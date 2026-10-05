# Auditoria: suporte a iPhone (05/10/2026)

Documento de trabalho; o app não lê este arquivo. Base: tag `v2.0.0` (411 testes
passando, `make lint` limpo), Immich servidor v3.2.4.

## Estado antes da mudança

A conexão do celular era uma tela só (`ui/widgets/phone.py`), usada em dois lugares:
o passo “Celular” do assistente (`ui/wizard/pages.py`, `PhonePage`) e a página Celulares
(`ui/pages/phones.py`). A página Rede leva ao QR de fora de casa (`show_away`).

| Ocorrência | Onde | Classificação |
|---|---|---|
| QR e botões Play Store / F-Droid | `widgets/phone.py`, `constants.py` | Android |
| “Battery → Unrestricted” | `widgets/phone.py` (`TIPS`) | Android (aparecia para todos) |
| “Choose the camera folder” (`Camera`, WhatsApp Images) | `widgets/phone.py` | Android (aparecia para todos) |
| “Turn on background backup” (botão que não existe mais no app atual) | `widgets/phone.py` | desatualizado |
| QR + endereço do servidor, “Copy address” | `widgets/phone.py` | compartilhado |
| Em casa (Wi-Fi) / Fora de casa (Tailscale) | `widgets/phone.py`, `pages/network.py` | compartilhado |
| “Use the same Wi-Fi” | `widgets/phone.py` | compartilhado |
| “QR codes to connect your Android phone” | AppStream | Android |
| `lan_ip()`: endereço da rota padrão | `core/system.py` | compartilhado — **errado com VPN** no computador (o QR mostrava o IP da VPN) |

Nenhum teste cobria a tela além da forma da lista `TIPS` e do QR em si.

## O que o Immich realmente faz no iPhone (fontes)

Conferido no código e na documentação do Immich (main de 05/10/2026, comparado com a
tag v3.2.4; os arquivos citados são iguais nas duas):

| Fato | Fonte | Uso no app |
|---|---|---|
| App Store: `https://apps.apple.com/us/app/immich/id1613945652` | `docs/docs/partials/_mobile-app-download.md` | `APP_STORE_URL` |
| iOS 15 ou mais novo | página da App Store; `Podfile` (`platform :ios, '15.0'`) | doc 16 |
| **Não há** deep link, universal link nem QR que preencha o endereço do servidor | `mobile/lib/services/deep_link.service.dart` (só `memory`, `asset`, `album`, `people`, `activity`); `login_form.dart` | QR com a URL + “Copiar endereço” (sem protocolo inventado) |
| Campo do login: “Server Endpoint URL” (pt-BR: “URL do servidor”) | `i18n/en.json` `login_form_endpoint_url` | texto do cartão do endereço |
| `http://` funciona (`NSAllowsArbitraryLoads`) | `mobile/ios/Runner/Info.plist` | endereço `http://…:2283` |
| Pede **Rede Local** “to connect to the local server using IP address” | `Info.plist` `NSLocalNetworkUsageDescription` | passo “Permita a Rede Local” e causa comum |
| Acesso limitado às fotos conta como acesso; o iOS só entrega as fotos escolhidas | `enums.dart` (`hasAccess`), comportamento do PhotoKit | passo “Permita o acesso a todas as fotos” |
| Segundo plano exige **Background App Refresh**; o iOS decide quando roda; abrir o app ajuda | `docs/docs/features/mobile-backup.md` | passo “Deixe o iOS continuar o backup” |
| Fotos só no iCloud são baixadas para o cache, enviadas e o cache é limpo; usa dados e espaço | `mobile-backup.md` (“iCloud Backup”), `foreground_upload.service.dart` | “Fotos no iCloud” |
| Live Photos: foto e vídeo enviados (vídeo primeiro) e ligados; originais sempre mantidos, sem compressão | `background_upload.service.dart`, README, FAQ | “O primeiro backup demora” (detalhes) |
| Backup: ícone de nuvem → “Select” → álbuns → “Enable Backup”; só Wi-Fi por padrão; chaves “Use cellular data…” para fotos e vídeos | `mobile-backup.md`, `backup.page.dart`, `backup_settings.dart` | passos 4–5 e “Backup pela rede móvel” |
| “Free Up Space”: só o que já está no servidor; lista antes; manda para “Apagados”; **no iPhone com iCloud, apaga do iCloud também** | `docs/docs/features/mobile-app.mdx` | “Precisa de espaço no iPhone?” |
| Tailscale iOS: `https://apps.apple.com/us/app/tailscale/id1470499037` | tailscale.com/download/ios | cartão “Instale o Tailscale” |

Não confirmado (vai para o plano de testes, doc 17): o nome do álbum com todas as fotos
na lista do Immich (“Recents”/“Recentes”); o texto exato do pedido de Rede Local na
versão atual do iOS; se o link da App Store com `/us` abre na loja do país da conta.

## Riscos

- Prometer no iPhone o comportamento do Android (backup contínuo). → Texto diz que o iOS
  decide; nada de “sempre”.
- “Liberar espaço” com Fotos do iCloud apaga do iCloud. → Explicado só sob demanda, com o
  aviso antes de qualquer outra coisa.
- Mostrar como “status” algo que o computador não vê (login, álbuns, backup ligado). →
  Passos numerados, com a frase “este computador não consegue vê-los”.
- Teste “o celular alcança o servidor” feito do computador. → Dois testes separados:
  “deste computador” (automático) e “pelo celular” (o próprio celular abre a página).
- VPN no computador mudando o endereço do QR. → `choose_lan_address`.

## Plano (executado)

1. `core/mobile.py`: descrição declarativa das plataformas (lojas, passos, dicas, causas).
2. `core/network.py`: escolha do endereço da rede de casa e diagnóstico puro.
3. `probe_server(url)` nos backends real e simulado; cenários `no-network`,
   `no-tailscale`, `lan-unreachable`.
4. `widgets/phone.py` reescrito em cima disso; `QrCode` com descrição acessível.
5. Testes de núcleo, de interface (GTK) e de i18n; capturas pelo `tools/tour.py`.
