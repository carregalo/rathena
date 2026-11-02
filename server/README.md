# Servidor do jogo novo

Um fork enxuto do código C++ do rAthena, com nome, build, configuração e banco de dados próprios.

Plano:

1. Mapear o código do rAthena e separar o motor (o que o jogo precisa) do conteúdo e dos sistemas do
   Ragnarok (o que sai). Resultado em `re/spec/server/`.
2. Copiar para cá só o necessário e fazer compilar e subir com um mapa de teste.
3. Remover um sistema por vez, recompilando e testando a cada passo.
4. Regras, personagem fixo e conteúdo do jogo novo.

O protocolo do cliente do Ragnarok é mantido no começo, para servir de referência na comparação com o
cliente oficial.

Licença: derivado do rAthena, portanto GPL (ver `LICENSE` na raiz).
