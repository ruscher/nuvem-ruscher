# 17 — Plano de testes: iPhone (e Android)

Documento de trabalho; o app não lê este arquivo. Tipos: **A** automatizado (`make test`),
**S** modo simulado (`--simulate`), **I** inspeção do código/documentação do Immich,
**P** pendente em aparelho real. Nenhum iPhone físico foi usado até aqui: tudo marcado
**P** está por fazer.

## Já coberto

| Caso | Tipo | Onde |
|---|---|---|
| Android padrão: QR e botões Play Store/F-Droid, dica de bateria | A | `test_phone_ui.py::test_android_is_the_default` |
| iPhone: QR e botão da App Store, Background App Refresh, Rede Local, iCloud; nada de Android | A | `test_iphone_switches_store_tips_and_remembers` |
| Trocar de plataforma e voltar; plataforma lembrada | A | idem, `test_saved_platform_is_restored` |
| Fora de casa: cartão do Tailscale da loja certa, endereço `*.ts.net` | A, S | `test_away_from_home_adds_tailscale` |
| Sem Tailscale: só “em casa” | A, S | `test_without_tailscale_only_home`, `--scenario no-tailscale` |
| Sem rede / IP inválido | A, S | `test_no_network`, `--scenario no-network` |
| Servidor sem resposta no endereço + firewall | A, S | `test_lan_unreachable_points_to_the_fix`, `--scenario lan-unreachable` |
| VPN no computador não troca o endereço do QR | A | `test_network.py::test_vpn_default_route_falls_back_to_the_home_network` |
| QR sem credenciais | A | `test_server_qr_never_carries_credentials` |
| Texto com “&” aparece (sem markup) | A | `test_plain_text_is_never_parsed_as_markup` |
| Janela estreita, claro e escuro | A, S | `test_narrow_and_dark`, `tour.py --narrow --dark` |
| URLs: App Store oficial; Android sem mudança | A, I | `test_mobile.py` |
| Live Photos (foto + vídeo), originais sem compressão, HEIC/MOV aceitos | I | ver auditoria |
| iCloud baixado para cache e limpo depois | I | ver auditoria |

## Em aparelho real (P)

Preparar: servidor no ar, uma conta por pessoa em Contas, página Celulares em “iPhone ou
iPad”. Anotar a versão do iOS e do app Immich (precisa casar *major.minor* com o servidor).

| # | Caso | Passos | Esperado |
|---|---|---|---|
| 1 | Instalação | Câmera no QR “Instale o Immich” | App Store abre no Immich, **na loja do país da conta** (o link tem `/us`) |
| 2 | Mesmo Wi-Fi | Câmera no QR do endereço | Safari abre a página de login do Immich |
| 3 | Primeiro acesso | No app, “URL do servidor” = endereço mostrado; e-mail e senha da conta | Entra; o iOS pede **Rede Local** — conferir o texto e que “Permitir” é preciso |
| 4 | Rede Local negada | Negar; tentar entrar | Falha; Ajustes → Privacidade e Segurança → Rede Local → Immich resolve |
| 5 | Fotos: acesso limitado | Escolher “Acesso Limitado” com 3 fotos | Só as 3 aparecem para backup |
| 6 | Fotos: acesso total | Ajustes → Immich → Fotos → Acesso Total | Biblioteca inteira disponível |
| 7 | Álbum com tudo | Nuvem → Selecionar | Confirmar o nome do álbum com todas as fotos (“Recentes”?) — ajustar o texto se for outro |
| 8 | Backup inicial | Ativar Backup com ~200 itens | Todos no servidor; tempo anotado |
| 9 | HEIC | Foto da câmera padrão | Chega como `.heic`, original intacto (comparar hash) |
| 10 | HEVC | Vídeo 4K | Chega como `.mov` HEVC, sem conversão |
| 11 | Live Photo | Foto com Live ligado | Foto + vídeo no servidor, tocando juntos |
| 12 | JPEG/PNG/MP4 | Imagem salva da web, captura de tela, vídeo baixado | Todos chegam |
| 13 | Vários álbuns | Incluir dois, excluir um (toque duplo) | Só os incluídos |
| 14 | Segundo plano | Background App Refresh ligado; app fechado; tirar fotos; esperar horas | Chegam em algum momento (o iOS decide); anotar quanto demora |
| 15 | Sem Background App Refresh | Desligar | Só envia com o app aberto |
| 16 | Fotos do iCloud + Otimizar | Biblioteca com originais só no iCloud | Baixa, envia, libera o cache; dados móveis só se ativados |
| 17 | Wi-Fi desligado | Só rede móvel, “Use a rede móvel” desligado | Não envia |
| 18 | Rede móvel ligada | Ativar “Use a rede móvel” fora de casa com Tailscale | Envia |
| 19 | Servidor desligado | Parar o servidor; abrir o app | Erro de conexão; ao religar, continua |
| 20 | IP mudou | Reiniciar o roteador (novo IP) | App falha; a página mostra o novo endereço; digitar de novo resolve |
| 21 | Fora de casa | Tailscale no iPhone (mesma conta), endereço `*.ts.net` | Entra e envia pela rede móvel |
| 22 | Outra pessoa | Segundo iPhone, outra conta | Bibliotecas separadas |
| 23 | Biblioteca grande | 10 mil+ itens | Termina; anotar tempo, bateria, espaço temporário |
| 24 | Duplicadas | Mesma foto duas vezes | O Immich não duplica (hash) |
| 25 | Liberar espaço com iCloud | Depois do backup, numa conta de teste | Confirma a remoção do iCloud e “Apagados” por 30 dias — **nunca na biblioteca real** |
| 26 | Rede de visitantes | iPhone na rede guest | Não alcança; a causa “Mesmo Wi-Fi” explica |
| 27 | VPN no iPhone | Ligar uma VPN comum | Não alcança em casa; a causa “VPN no celular” explica |
| 28 | iPad | Repetir 1–8 num iPad | Igual |
| 29 | Android | Repetir 1–3, 8, 14 num Android | Nada mudou em relação à v2.0.0 |

Leitor de tela e teclado (no computador, **S**): Orca lendo os QR (“Instalar o Immich pela
App Store: …”), os botões das lojas e o resultado do teste; Tab percorre seletores,
botões das lojas, copiar, testar e as linhas recolhidas.
