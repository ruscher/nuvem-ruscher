# 11 — Pastas compartilhadas

Documento de trabalho; o app não lê este arquivo. Conferido no código da v3.2.4.

## Mapeamento

| Na interface | No Immich |
|---|---|
| Pasta compartilhada | Álbum compartilhado |
| Dono | `albumUsers[].role = owner` (quem criou) |
| Pode adicionar | `editor` |
| Só ver | `viewer` |
| Compartilhar toda a biblioteca | Partner sharing (`/partners`, uma direção) |

Não há abstração própria: tudo o que a interface mostra vem da API, e o que ela faz é uma
chamada da API. Abrir no Immich leva ao álbum (`/albums/{id}`).

## O que cada papel faz de verdade (código, não só a documentação)

| | Dono | Pode adicionar (editor) | Só ver (viewer) |
|---|---|---|---|
| Ver e baixar | sim | sim | sim |
| Adicionar fotos | sim | sim | não |
| Renomear / descrição | sim | sim | não |
| Convidar, trocar papel, remover outras pessoas | sim | **sim** | não |
| Remover fotos | qualquer | só as próprias | não |
| Excluir a pasta | sim | não | não |

A interface diz exatamente isso (o editor também pode convidar pessoas).

## Escopo

Álbuns pertencem a quem os criou e a API não dá acesso de administrador aos álbuns dos
outros. A página **Compartilhamento** trabalha com a conta conectada (a mesma sessão de
administrador da página Contas, ou qualquer conta): "Compartilhado por você" (`isOwned=true`,
`isShared=true`), "Compartilhado com você" (`isOwned=false`) e "Bibliotecas inteiras"
(partners nas duas direções).

## Bibliotecas externas

O app não cria a mesma pasta física como biblioteca externa de várias contas: no Immich
uma biblioteca externa tem **um** dono, que não muda, e duas bibliotecas na mesma pasta
viram fotos duplicadas e independentes. Para uma pasta física comum: uma conta é dona da
biblioteca e compartilha por álbum ou por partner sharing.
