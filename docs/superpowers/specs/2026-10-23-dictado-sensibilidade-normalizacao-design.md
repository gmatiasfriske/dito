# Dictado — Sensibilidade, normalização de áudio e visual de transcrição

**Data:** 23/10/2026
**Status:** aprovado pelo usuário (caminho A, com ffmpeg)

## Intenção

Melhorar o ditado em voz baixa e a qualidade do áudio antes da transcrição, preservando o resultado que o usuário já gosta no “Nivelar” do editor ApexEdit. Além disso, deixar o processamento visualmente mais limpo: pílula circular enquanto transcreve, progresso laranja no perímetro e o texto transcrito aparecendo por alguns segundos.

## Objetivos

1. Controle de sensibilidade visível durante a gravação, ajustável pela rodinha do mouse, sem clique.
2. A onda de áudio acompanhar a sensibilidade efetiva.
3. Normalização fiel à cadeia do editor: gate de silêncio + compressor + EBU R128 loudnorm dual-pass.
4. Salvar, a cada gravação, o áudio original e o áudio processado em `audios_teste/`.
5. Ao parar a gravação, voltar a pílula para o círculo, desenhar o progresso laranja no perímetro e mostrar o trecho transcrito por ~2 s.

## Não objetivos

- Não alterar o modelo, o idioma, o atalho ou o fluxo de colagem.
- Não persistir a sensibilidade no `dictado_config.json`; ela vale só na sessão e volta ao padrão ao reabrir.
- Não refazer a interface clássica (Tk) nesta rodada; o slider é da interface nativa.
- Não resolver agora o empacotamento do ffmpeg no executável final; o teste usa o ffmpeg do `.venv` via `imageio-ffmpeg` e tem fallback para o editor.

## Restrições

- Áudio do app: mono, 16 kHz, `float32`.
- Sensibilidade: 7 níveis; padrão 4/7; nível maior = mais sensível.
- Normalização: alvo −23 LUFS, força `suave` (mesmo padrão do editor), TP −1,5 dB, LRA 11.
- Gate antes do loudnorm; a sensibilidade da sessão também desloca o limiar do gate em dB.
- Arquivos de teste não podem entrar no Git.
- Testes existentes usam `unittest`; manter o padrão.
- A interface nativa é a ativa; `ClassicWidget` recebe um no-op para não quebrar o fallback.

## Abordagens consideradas

### Normalização

**A — ffmpeg + gate em Python (escolhida).** Portar o gate do editor para numpy (detecção e aplicação) e usar o ffmpeg para o compressor + loudnorm dual-pass. É a opção mais fiel ao “Nivelar”, reaproveita a cadeia já validada e permite testar o resultado exato. Custo: dependência `imageio-ffmpeg` (~100 MB no `.venv`) e um processo externo.

**B — tudo em Python.** Portar também o loudnorm/compressor. Evita ffmpeg, mas não reproduz o EBU R128 dual-pass com a mesma fidelidade e aumenta muito o código de DSP.

**C — só noisereduce + pico.** Menor esforço, mas não entrega o resultado do editor; descartada.

### Sensibilidade

**A — slider de 7 níveis na pílula (escolhida).** Trilho fino abaixo da onda, knob e 7 marcas; roda do mouse muda um nível. Discrição e previsibilidade.

**B — botões +/−.** Mais óbvio, porém o usuário pediu slider e os botões ocupariam a toolbar.

**C — só no diálogo de ajustes.** Não atende ao uso durante a gravação.

### Visual de processamento

**A — círculo + arco laranja (escolhida).** A pílula volta a `IDLE_W` ao parar; o progresso vira um arco no perímetro; ao terminar, o texto aparece na pílula expandida por 2 s e ela recolhe.

**B — manter a pílula retangular e só mover a barra para o perímetro.** Menos dramático; o usuário pediu o retorno ao círculo.

## Decisões

- `imageio-ffmpeg==0.6.0` em `requirements.txt`; `find_ffmpeg()` procura, nesta ordem: `DICTADO_FFMPEG`, `imageio_ffmpeg.get_ffmpeg_exe()`, ffmpeg do editor, `shutil.which("ffmpeg")`.
- Gate: janelas de 25 ms no sample rate nativo; piso = percentil 10 ignorando 0,4 s; margem 12/8/10 dB; limiar `floor + margin + sens_db`, limitado a −55..−20 dB; histerese 6 dB; silêncio mínimo 0,15 s; merge de buracos <0,12 s; encolhe 0,04/0,08 s; mínimo 0,08 s; fades 30 ms na saída e 15 ms na entrada.
- `sens_db` da sessão: `(4 - nível) * 2.0` (−6 dB no nível 7, +6 dB no nível 1).
- Loudnorm: `acompressor` conforme força `suave` (`threshold=-16dB:ratio=2:attack=25:release=300:makeup=1`), `loudnorm=I=-23:TP=-1.5:LRA=11`, medição e aplicação com `linear=true`, sem `offset`.
- Sensibilidade efetiva: `silence * fator` e `voice * fator`, com `voice >= silence * 1.5`; fatores `(2.0, 1.6, 1.25, 1.0, 0.8, 0.63, 0.5)`, nível 4 = 1,0.
- A onda e o `_vad_trim` usam os limiares efetivos; a sensibilidade não é salva no config.
- Áudios: `audios_teste/AAAAMMDD_HHMMSS_original.wav` e `..._processado.wav`; original antes do denoise, processado depois de gate + loudnorm e antes do chunking.
- Visual: `STATE_PROCESSING` usa `IDLE_W`; arco laranja no perímetro; `STATE_READY` com status expande e o status é limpo após 2000 ms.
- Rodinha: tratar `WM_MOUSEWHEEL` quando o cursor estiver sobre o conteúdo e a gravação estiver ativa. Se o Windows não entregar a mensagem por a janela ser `WS_EX_NOACTIVATE`, a contingência é um hook `WH_MOUSE_LL`; verificar manualmente antes de considerar pronto.

## Critérios de aceite

- Durante a gravação, o slider aparece abaixo da onda; a roda muda o nível sem clique; a onda muda de escala junto.
- O nível escolhido continua entre gravações na mesma sessão e volta a 4/7 ao reabrir.
- Áudio processado passa por gate + loudnorm; o original e o processado são salvos e audíveis.
- Se o ffmpeg falhar, o app não cai: registra o erro, usa o áudio com gate (ou o denoised) e continua.
- Ao parar, a pílula volta ao círculo com arco laranja; ao terminar, o texto aparece por ~2 s e a pílula recolhe.
- Testes unitários existentes e novos passam; nenhum áudio/log pessoal é adicionado ao Git.
