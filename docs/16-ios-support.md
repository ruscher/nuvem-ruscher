# 16 — Celulares: Android e iPhone

Documento de trabalho; o app não lê este arquivo. Fontes de cada afirmação sobre o
Immich: [ios-support-audit.md](ios-support-audit.md).

## Fluxo

```
Qual celular?   [ Android | iPhone ou iPad ]          (lembrado entre aberturas)
De onde?        [ Em casa (Wi-Fi) | Fora de casa ]    (só com o Tailscale ligado aqui)

1. Instale o Immich      QR da loja da plataforma + botões das lojas
(2. Instale o Tailscale) só fora de casa: QR da loja da plataforma + “mesma conta”
2/3. Digite este endereço no Immich   QR + endereço selecionável + Copiar

Depois, no app do Immich   (passos no celular; o computador não os vê)
  1 Entre com a sua conta · 2 Acesso a todas as fotos · [iPhone: Rede Local]
  · Escolha o que proteger · Ativar Backup · segundo plano (bateria / Background App Refresh)

Conferir a conexão
  Testar deste computador [Testar] → resultado e o que fazer (botão para a página certa)
  Testar pelo celular: apontar a câmera para o QR do endereço; a página do Immich abre
  O celular não conecta? (recolhido) → causas comuns da plataforma e do modo

Bom saber (recolhidos): primeiro backup · iCloud (iPhone) · liberar espaço · rede móvel
```

Android e iPhone usam a mesma tela; muda só o conteúdo. Nada de Android aparece no iPhone
e vice-versa (testado).

## Arquitetura

- **`core/mobile.py`** — `MobilePlatform` (dataclass congelada): `stores`, `tailscale`,
  `photos`, `albums`, `background`, `permissions`, `good_to_know`, `trouble`. Cada item é
  uma `Note` (ícone, título, texto, detalhes opcionais) com textos `N_()`. Funções
  `phone_steps`, `good_to_know`, `troubleshooting` montam as listas; `platform(id)` cai
  no Android para qualquer valor desconhecido. Adicionar iPad separado, por exemplo, é
  uma entrada nova, sem tocar na interface.
- **`core/network.py`** — `address_kind`, `choose_lan_address` (com VPN como rota padrão,
  usa o endereço privado de uma interface de verdade), `diagnose(Facts) → Diagnosis`.
  Puro, sem rede: os fatos vêm do backend.
- **Backend** — `probe_server(url)`: `GET {url}/api/server/ping` com 4 s de limite. No
  simulado, responde conforme o cenário.
- **`ui/widgets/phone.py`** — `PhoneView(backend, show_title, open_page)`. Monta tudo a
  partir de `core.mobile`; reconstrói cartões e grupos ao trocar plataforma ou modo.
  `open_page` existe na página Celulares (botões “Abrir Rede/Início/Sistema”) e não no
  assistente.

## Decisões

| Decisão | Por quê |
|---|---|
| Sem deep link para o endereço | O app oficial não tem (só memória/foto/álbum/pessoa). Inventar quebraria em silêncio. |
| QR do endereço = URL `http://…:2283` | Funciona nos dois sistemas; escaneado, abre a página do Immich no navegador — o teste real “o celular alcança o servidor”. |
| Dois testes, com nomes diferentes | O computador só prova que o servidor responde no endereço; quem prova o caminho do celular é o celular. |
| Firewall e endereço público são **avisos** | Um teste feito do próprio computador não passa pelo firewall; não dá para reprovar nem aprovar. |
| Passos do celular como lista numerada, sem ✓ | O computador não vê login, álbuns nem backup ligado; um ✓ seria dado falso. |
| iCloud e “Liberar espaço” recolhidos | Informação séria, mas não é para todos: aparece ao abrir, com o aviso do iCloud primeiro. |
| “Recentes” no iPhone, “Camera” no Android | O álbum com tudo em cada sistema (no iPhone, a confirmar no aparelho — doc 17). |
| F-Droid continua `f-droid.org/packages/app.alextran.immich/` | Pedido: URLs do Android sem mudança. A documentação do Immich hoje aponta o repositório F-Droid da FUTO (`get.immich.app/fdroid`); ver sugestões. |
| Nomes do app e do iOS na tradução | O pt-BR usa os rótulos que a pessoa vê: “URL do servidor”, “Selecionar”, “Ativar Backup”, “Liberar espaço” (i18n do Immich v3.2.4), “Ajustes → Geral → Atualização em 2º Plano”. |
| Linhas sem markup, texto definido depois | “Privacy & Security” como markup some da tela; no construtor, o libadwaita lê o texto antes de `use_markup=False` valer. |

## Acessibilidade

- Cada QR tem nome acessível com a finalidade e o conteúdo (“Instalar o Immich pela App
  Store: https://…”); o endereço também é texto selecionável, com botão de copiar.
- Botões das lojas com nome e dica (“Abrir o Immich na App Store”).
- Seletores (`Adw.ToggleGroup`) com nome acessível; títulos dos cartões com papel de título.
- Resultado do teste anunciado ao leitor de tela (GTK ≥ 4.14) e foco no primeiro resultado.
- Estado sempre com ícone **e** texto; nada só por cor.
- Janela estreita: cada cartão numa linha, centralizado (testado a 360 px, claro e escuro).

## Segurança

O QR do servidor leva só a URL (`http://<ip>:2283` ou o nome Tailscale). Nada de senha,
token ou chave; nenhuma porta é aberta sozinha; fora de casa continua só pelo Tailscale.
Testado: o QR nunca contém `@` nem “key”.

## Resultado

- 52 testes novos (`test_mobile.py`, `test_network.py`, `test_phone_ui.py`), 463 no total.
- Capturas: `python3 tools/tour.py build/x --scenario installed --extra phones`
  (também `--scenario lan-unreachable`, `--narrow`, `--dark`).
