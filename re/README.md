# Engenharia reversa

Base técnica do jogo novo: como o servidor (rAthena) e o cliente do Ragnarok funcionam, para escrever um
servidor derivado (`server/`) e um cliente novo em Unity (`client/`).

| Pasta | O que guarda | No git? |
| --- | --- | --- |
| `private/` | Material bruto da análise do cliente da Gravity: projeto do Ghidra, código descompilado, anotações cruas, capturas com dados pessoais | **Não** |
| `spec/` | Especificações escritas com palavras próprias: protocolo, fluxos, máquinas de estado, fórmulas, constantes medidas | Sim |
| `tools/` | Ferramentas próprias: proxy espião, gerador de protocolo, scripts de análise | Sim |

## Regras de sala limpa

1. O executável da Gravity é analisado só para **entender** o comportamento.
2. O que sai da análise é escrito em `spec/` com palavras próprias: o que acontece, em que ordem, com que números.
   Nunca se copia código descompilado para `spec/`, `server/` ou `client/`.
3. O cliente novo é escrito **somente** a partir de `spec/`.
4. Nenhum arquivo da Gravity (arte, sons, mapas, textos, executáveis) entra no jogo. Os dados do cliente
   oficial só servem para medir números.
