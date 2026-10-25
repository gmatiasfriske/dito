# Modelos para testar no futuro

## Underdog Bark 3.0

Pesquisado em **25/10/2026**.

- Site: https://underdog.ai/bark
- Família: Bark 3.0 Clean, 3.0, 3.0 Plus e 3.0 Pro.
- Tamanhos: 163–180 MB (versões normais) e 1,25 GB (Pro).
- Licença: CC-BY 4.0.
- Base: NVIDIA Parakeet (`nvidia/parakeet-tdt-0.6b-v3` e
  `moondream/parakeet-ultra`).
- Ponto forte: muito rápido e leve; a página informa ~595× tempo real em
  um MacBook Pro M5 Max.
- Limitação atual: **English only**. A própria Underdog indica Whisper
  Large v3 Turbo para outros idiomas.
- Não foram encontrados fine-tunes públicos em português brasileiro nas
  buscas feitas até esta data.
- Sem timestamps por palavra e sem identificação de falantes no Bark 3.0.

### O que acompanhar

O usuário acredita que podem surgir treinamentos em português nos próximos
dias ou semanas. Quando aparecer um fine-tune pt-BR (ou uma versão oficial
multilíngue), testar contra o CrisperWhisper 2.0 large:

- WER em fala espontânea brasileira, incluindo sotaques e fala baixa;
- pontuação, acentos e correção de disfluências;
- velocidade e uso de VRAM;
- timestamps por palavra, se o Dito passar a usar;
- licença e tamanho do pacote.

Se o resultado for melhor e o modelo continuar leve, vale considerar como
alternativa ao CrisperWhisper no futuro. Nada foi alterado no Dito 1.0.
