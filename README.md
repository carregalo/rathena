# Jogo de fã online no Condado (experimental)

Um jogo online no formato cliente/servidor do Ragnarok Online, ambientado no Senhor dos Anéis como **obra de
fã experimental, sem fins comerciais**. Os nomes do Senhor dos Anéis pertencem aos seus detentores; toda a
arte do jogo é original.

| Pasta | O que é |
| --- | --- |
| `server/` | O servidor: um fork enxuto do [rAthena](https://github.com/rathena/rathena) (C++, GPL) |
| `client/` | O cliente novo, em Unity (C#), escrito a partir das especificações em `re/spec/` |
| `re/` | Engenharia reversa do servidor e do cliente do Ragnarok, em sala limpa (ver `re/README.md`) |
| `docs/` | Análise das mecânicas do Ragnarok usadas como referência de design |
| `tests/` | Checklist da alpha |

Nada da Gravity (arte, sons, mapas, textos, executáveis) faz parte do jogo.

Licença: o servidor é derivado do rAthena e continua GPL (`LICENSE`).
