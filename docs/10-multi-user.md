# 10 — Várias contas

Documento de trabalho; o app não lê este arquivo. Conferido na OpenAPI da v3.2.4.

## Decisão

Uma instalação do Immich, várias contas do Immich (cada uma com login, biblioteca,
dispositivos, álbuns e quota próprios). Nada de várias instalações, nada de mexer no
Postgres: só a API de administração.

## Sessão de administrador

Gerenciar contas exige um administrador. O app **não grava** credencial com esse poder:
o administrador entra (e-mail + senha) quando abre a página Contas; o `accessToken` do
`POST /auth/login` fica só na memória e o app faz `POST /auth/logout` ao sair ou ao fechar.
A chave salva em disco continua sendo a de estatísticas (ADR-010).

## Operações

| Interface | API |
|---|---|
| Listar (com uso e quota) | `GET /admin/users?withDeleted=true` + `GET /server/statistics` (`usageByUser`: fotos, vídeos, bytes) |
| Criar | `POST /admin/users` {name, email, password, `shouldChangePassword: true`, `quotaSizeInBytes` (null = ilimitado), `storageLabel`, `isAdmin`} |
| Editar nome/quota/rótulo/admin | `PUT /admin/users/{id}` |
| Nova senha temporária | `PUT /admin/users/{id}` {password: gerada, `shouldChangePassword: true`} (é o que a interface web do Immich faz; não há endpoint de reset) |
| Desativar | `DELETE /admin/users/{id}` sem `force` — a conta para de entrar na hora; o Immich apaga de vez depois de `user.deleteDelay` dias (padrão 7). A interface diz isso com essas palavras. |
| Reativar | `POST /admin/users/{id}/restore` (enquanto o prazo não acabou) |
| Excluir na hora | **não oferecido** (`force: true` apaga as fotos da pessoa sem volta) |

Regras do Immich respeitadas na interface: não dá para desativar a própria conta nem
mudar o próprio status de administrador (opções desligadas, com explicação); e-mail e
rótulo de armazenamento são únicos (erro 400 vira mensagem humana).

Quotas: Ilimitado, 10/25/50/100/250/500 GB, 1 TB, Personalizado → `quotaSizeInBytes`.
"Uso" = `quotaUsageInBytes` da conta (o que o Immich conta para a quota); fotos e vídeos =
`usageByUser`. Bibliotecas externas não contam na quota (documentação do Immich).

Senha inicial: gerada pelo app (16 caracteres, `secrets`), mostrada uma vez com botão de
copiar; `shouldChangePassword` obriga a troca no primeiro acesso.

Depois de criar: endereço do servidor + e-mail + QR do endereço para o app do celular.
