# 03 — Design e UX

Segue o [GNOME HIG](https://developer.gnome.org/hig/) com libadwaita 1.9.

## Design system

### Cores

O app **não inventa uma paleta de interface**: usa as variáveis do libadwaita, então
respeita automaticamente tema claro/escuro e a **cor de destaque do sistema**.

| Uso | Token libadwaita |
|---|---|
| Ação principal, links, anéis de progresso | `--accent-bg-color` / `--accent-color` |
| Sucesso (item verificado, servidor no ar) | `--success-color` |
| Aviso (NTFS, firewall) | `--warning-color` |
| Erro / ação destrutiva | `--error-color`, `.destructive-action` |
| Cartões | `.card`, `--card-bg-color` |
| Texto secundário | `.dim-label` (opacidade 55 %) |

Cores **próprias** só nas ilustrações e no ícone (identidade):

| Nome | Hex | Uso |
|---|---|---|
| Céu | `#3584E4` → `#62A0EA` | gradiente da nuvem |
| Nuvem | `#FFFFFF` / `#DEDDDA` | corpo e sombra |
| Pôr do sol | `#F6D32D` → `#FF7800` | foto 1 |
| Folha | `#57E389` → `#26A269` | foto 2 |
| Uva | `#C061CB` → `#813D9C` | foto 3 |

Todas da paleta oficial GNOME, harmonizam com qualquer destaque.

### Tipografia

Fonte da interface do sistema (nenhuma fonte embarcada). Classes do libadwaita:
`title-1` (tela de impacto), `title-2` (título de etapa), `title-4` (seções),
`heading`, `body`, `caption`, `monospace` (endereços, logs), `numeric` (números
que mudam — evita “pulos” de largura).

### Espaçamento

Grade de **6 px**: 6 · 12 · 18 · 24 · 36 · 48. Conteúdo centralizado com
`AdwClamp` (máx. 560 px no assistente, 860 px no painel). Margens laterais de 12 px
em telas estreitas.

### Ícones

- Ícone do app: SVG original (nuvem com três fotos em leque), em
  `data/icons/hicolor/scalable/apps/` + versão simbólica.
- Ícones simbólicos do Adwaita (`*-symbolic`), que recolorem com o tema.

### Animações

- Transições do `AdwNavigationView` (deslizar) entre etapas.
- Checklist: cada item entra de “aguardando” → spinner → ✓/⚠ com
  `Gtk.Revealer` (crossfade 200 ms).
- Progresso: `Gtk.ProgressBar` com valor interpolado (`AdwTimedAnimation`, 250 ms,
  `EASE_OUT_CUBIC`) — nunca “salta”.
- Celebração: confete desenhado em `Gtk.DrawingArea`, ~2,5 s, 90 partículas, com
  gravidade e rotação; termina sozinho.
- **Respeita “reduzir animações”**: se `gtk-enable-animations` = falso, o confete não
  é exibido e as transições são instantâneas.

## Telas (wireframes em texto)

### 1. Boas-vindas
```
┌────────────────────────────────────────────┐
│                                       ≡    │
│          [ilustração: nuvem + 3 fotos]     │
│                                            │
│        Suas fotos, na sua casa.            │  title-1
│  Vamos transformar este computador num     │
│  “Google Fotos” só seu. Leva poucos        │
│  minutos e nada do que já está no disco    │
│  será apagado.                             │
│                                            │
│              [  Começar  ]                 │  pill, suggested-action
│     Já entende do assunto? Ver detalhes ▸  │
└────────────────────────────────────────────┘
```

### 2. Verificação do sistema
```
  ← Verificação                        Passo 1 de 6
  Preparando o terreno
  ┌──────────────────────────────────────────┐
  │ ✓ Docker instalado                       │
  │ ✓ Docker ligado                          │
  │ ⚠ Seu usuário pode usar o Docker  [Corrigir] │
  │ ✓ Memória: 46 GB (mínimo 6 GB)           │
  │ ◌ Espaço livre no disco do sistema       │
  │ ✓ Porta 2283 livre                       │
  │ ✓ Conectado à internet                   │
  │ ℹ Firewall ativo (ufw)        [Liberar]  │
  └──────────────────────────────────────────┘
                       [ Verificar de novo ] [ Continuar ]
```
“Continuar” só habilita quando não há itens bloqueantes (⚠ informativos não
bloqueiam).

### 3. Armazenamento
```
  Onde suas fotos vão morar
  ┌ 🖴 Novo volume ───────────────────────────┐
  │  1,8 TB livres de 1,8 TB  [▓░░░░░░░░░░]  │
  │  /run/media/ruscher/Novo volume/immich-…  │
  │  Sistema de arquivos: NTFS (Windows)      │
  │                         [Escolher outra…] │
  └───────────────────────────────────────────┘
  ┌ ⚠ Disco formatado no Windows (NTFS) ──────┐
  │ Funciona bem para guardar fotos. Só três   │
  │ cuidados: … [Entender melhor ▾]            │
  └───────────────────────────────────────────┘
  ┌ Ligar o disco junto com o computador  [◯] │
  │ Para o servidor funcionar depois de        │
  │ reiniciar, mesmo antes de você entrar…     │
  │ ▸ Detalhes técnicos (linha do fstab)       │
  └───────────────────────────────────────────┘
  ℹ O banco de dados fica no disco interno.
```

### 4. Configuração
```
  Ajustes finais
  Fuso horário            America/Sao_Paulo   (detectado)
  Versão do Immich        v3.2.4 (mais recente) ▾
  ▸ Opções avançadas
      Vídeos mais rápidos com a placa de vídeo (AMD)   [●]
      Reconhecimento de rostos e busca inteligente     [●]
      Usar a placa de vídeo para a inteligência artificial [◯]
                                           [ Instalar ]
```

### 5. Instalação
```
  Instalando sua nuvem
  ✓ Preparando a configuração
  ◐ Baixando os componentes   1,2 GB de 2,9 GB · 18 MB/s
    [▓▓▓▓▓▓▓▓░░░░░░░░░░░░]  41 %
  ○ Ligando o servidor
  ○ Aguardando o servidor ficar pronto
  ▸ Detalhes técnicos (log)
                                   [ Cancelar ]
```
Falha: o item vira ✗, aparece a explicação humana e “Tentar novamente”.
Cancelado: “Instalação pausada. Você pode continuar de onde parou.” [Continuar].

### 6. Conta
```
  Crie sua conta de administrador
  Seu nome        [ Rafael              ]
  E-mail          [ voce@exemplo.com    ]
  Senha           [ ••••••••••   👁 ]  força: boa
  Confirmar senha [ ••••••••••       ]
  [✓] Mostrar contagem de fotos no painel
                               [ Criar conta ]
```

### 7. Celular
```
  Conecte seu celular
  ┌─ 1. Instale o app ─┐   ┌─ 2. Endereço do servidor ─┐
  │  [QR Play Store]   │   │   [QR http://192.168…]    │
  │ [Play Store][F-Droid]│ │ http://192.168.0.10:2283 ⧉│
  └────────────────────┘   └───────────────────────────┘
  Dicas para nunca perder uma foto
   🔋 Desative a otimização de bateria para o Immich
   📁 Em Backup, escolha a pasta “Camera”
   📶 Envie só no Wi-Fi para economizar dados
                                     [ Concluir ]
```
Em telas estreitas (`AdwBreakpoint` ≤ 600 px) os dois cartões ficam empilhados.

### 8. Celebração
```
          ✨ confete ✨
     [ilustração da nuvem com ✓]
       Sua nuvem está no ar!
   Agora é só abrir o app no celular.
   [ Abrir o Immich ]  [ Ir para o painel ]
```

### Painel
```
 ┌ Nuvem Ruscher ── [Visão geral|Celular|Registros|Backups|Atualizações|Mais] ≡ ┐
 │ ● No ar · http://192.168.0.10:2283            [Abrir] [Parar] [⟳]          │
 │ ┌ Fotos ┐ ┌ Vídeos ┐ ┌ Disco ──────────────────┐                          │
 │ │ 12.430 │ │   318 │ │ 210 GB usados · 1,6 TB livres                       │
 │ └────────┘ └───────┘ └─────────────────────────┘                          │
 │ Componentes                                                               │
 │  Servidor              saudável   CPU 2 %  RAM 410 MB                     │
 │  Inteligência artificial saudável CPU 0 %  RAM 1,1 GB                     │
 │  Banco de dados        saudável   …                                       │
 │  Cache                 saudável   …                                       │
 └───────────────────────────────────────────────────────────────────────────┘
```
Em janela estreita, as abas vão para uma barra inferior (`AdwViewSwitcherBar`).

## Microcopy (pt-BR)

Tom: próximo, calmo, concreto. Verbos no imperativo nos botões. Nunca “erro fatal”,
“falha catastrófica”, “exceção”.

| Situação | Texto |
|---|---|
| Docker ausente | **O Docker não está instalado.** É o programa que roda o servidor de fotos. [Instalar] |
| Docker parado | **O Docker está desligado.** [Ligar e manter ligado] |
| Fora do grupo | **Seu usuário ainda não pode usar o Docker.** [Permitir] |
| Grupo pendente | **Permissão concedida.** Funciona já; recomendamos sair e entrar na sessão depois. |
| Pouca RAM | **Memória abaixo do recomendado (4 GB).** Dá para usar com o reconhecimento de rostos desligado. |
| Porta ocupada | **Outro programa está usando a porta 2283.** Feche-o ou pare o outro Immich. Detalhes: {processo} |
| Sem internet | **Sem conexão com a internet.** Ela só é necessária para baixar os componentes. |
| Disco desmontado | **O disco “Novo volume” não está conectado.** Conecte-o e o servidor liga sozinho. |
| NTFS | **Disco formatado no Windows (NTFS).** Funciona bem para guardar fotos. Três cuidados: … |
| FAT32 | **Este disco não aceita arquivos maiores que 4 GB.** Vídeos longos podem não ser salvos. |
| Biblioteca existente | **Encontramos fotos de uma instalação anterior.** Elas serão reaproveitadas — nada será apagado. |
| Falha no download | **O download foi interrompido.** Verifique a internet e toque em “Tentar novamente” — ele continua de onde parou. |
| Desinstalar | **Remover o servidor do Immich?** Suas fotos e vídeos **continuam no disco** e não serão apagados. |

## Estados

| Estado | Tratamento |
|---|---|
| Carregando | `AdwSpinner` + texto do que está acontecendo (“Procurando discos…”) |
| Vazio (sem backups) | `AdwStatusPage`: “Nenhum backup ainda” + “O Immich faz um todo dia às 2h” + [Fazer agora] |
| Vazio (logs) | “Nada por aqui ainda. Os registros aparecem quando o servidor está ligado.” |
| Erro | `AdwStatusPage`/`AdwBanner` com: o que aconteceu · o que fazer · [ação] · ▸ detalhes técnicos |
| Servidor parado | Banner no topo do painel: “O servidor está desligado.” [Ligar] |
| Disco ausente | Banner de aviso com o nome do disco e explicação |

## Acessibilidade

- Navegação completa por teclado: `Tab`/`Shift+Tab`, `Enter` ativa a ação padrão de
  cada etapa (`set_default_widget`), `Alt+←` volta, `Esc` fecha diálogos,
  `Ctrl+Q` sai, `Ctrl+1…6` trocam abas do painel, `F5` atualiza.
- Rótulos acessíveis (`update_property([Gtk.AccessibleProperty.LABEL], …)`) em
  todos os botões só com ícone, no QR (“Código QR com o endereço …”) e nos ícones
  de status (ex.: “Concluído”, “Atenção”).
- Status nunca comunicado só por cor: ícone + texto.
- Contraste herdado do libadwaita (WCAG AA); textos sobre ilustração evitados.
- Animações desligáveis pelo sistema.
- Fontes e tamanhos do sistema; nenhum tamanho fixo em px para texto.
