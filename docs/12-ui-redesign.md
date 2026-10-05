# 12 — Nova interface (v2)

Documento de trabalho; o app não lê este arquivo.

## Referência

`/usr/share/gitrepo/build_iso` (big-comm): `Adw.OverlaySplitView` com barra lateral de
`ActionRow` em `.navigation-sidebar`, faixa "hero" com gradiente no topo de cada página,
corpo em `Adw.Clamp` (920/760), seções `Adw.PreferencesGroup` com título e descrição,
opções técnicas dentro de `Adw.ExpanderRow` "Avançado", rodapé fixo com a ação principal,
cores só por variáveis do libadwaita. Pegamos a estrutura; a identidade é nossa (gradiente
céu → verde-água, ícones de nuvem), e acrescentamos o que lá não existe: colapso em janela
estreita (`Adw.Breakpoint`), seletor de tema e páginas pensadas para leigos.

## Navegação

| Página | Para quê | Antes |
|---|---|---|
| **Início** | "Sua nuvem": está tudo bem? números, espaço, saúde (servidor, armazenamento, redundância, backups, contas, rede) e atalhos | Início |
| **Celulares** | conectar o app do Immich (QR) | Celular |
| **Contas** | pessoas da família, quotas | novo |
| **Compartilhamento** | pastas compartilhadas | novo |
| **Armazenamento** | local das fotos (trocar), redundância (RAID), discos e saúde | parte de Mais |
| **Backups** | backups do banco; "RAID não é backup" | Backups |
| **Rede** | endereço em casa, Tailscale, firewall | parte de Mais |
| **Atualizações** | versão do Immich | Atualizar |
| **Sistema** | registros, serviço, configuração, detalhes técnicos, desinstalar | Registros + Mais |

Preferências (menu): aparência **Sistema / Claro / Escuro** (`Adw.StyleManager`), guardada
no estado do usuário.

## Regras de layout

- Hero: ícone 48 px, `title-1`, descrição; quebra linha, nunca corta texto.
- Corpo: clamp 920 (aperta a partir de 760), margens 20/24/28, seções com 24 px entre si.
- Janela ≤ 760 sp: barra lateral vira sobreposição com botão de mostrar; ≤ 480 sp, grades de
  cartões viram uma coluna (`Adw.WrapBox`).
- Estados sempre com ícone **e** texto (nunca só cor). Pílulas de estado: ok, ocupado,
  aviso, erro, parado.
- Técnico fica em "Avançado" (`ExpanderRow`) ou na página Sistema.
- Erros: título humano + o que fazer + "Detalhes técnicos" recolhidos.
- Nada de chamada bloqueante na thread da interface (`run_async`/`Operation`).
