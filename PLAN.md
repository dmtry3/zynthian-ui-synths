# План развития виджетов (`zynthian-ui-synths`)

Дорожная карта кастомных тачскрин-виджетов для Zynthian V5 (800×480) в единой дизайн-системе [GEMINI.md](GEMINI.md).

---

## ✅ Готовые виджеты (Синтезаторы)

- [x] **Surge XT** (`zynthian_widget_surge_xt.py`)
- [x] **Monique** (`zynthian_widget_monique.py`)
- [x] **Vitalium** (`zynthian_widget_vitalium.py`)
- [x] **Vaporizer2** (`zynthian_widget_vaporizer2.py`)
- [x] **Dexed** (`zynthian_widget_dexed.py`)

---

## 🎯 Приоритет 1 — Modulation FX (Топ выбора)

- [ ] **ChowPhaserStereo** (`https://github.com/jatinchowdhury18/ChowPhaserStereo`)
  - *Идея UI*: визуализация стерео-фазовых ступеней и LFO-модуляции, 2D-пэд `Center Freq × Feedback`, переключение числа ступеней и нелинейности.
- [x] **YK Chorus** (`zynthian_widget_yk_chorus.py`)
- [x] **Calf Multi Chorus** (`zynthian_widget_calf_multi_chorus.py`)
- [ ] **Tal-Filter-2** (`urn:juce:TalFilter2`)
  - *Идея UI*: интерактивный редактор огибающей модуляции, выбор режима (`LP/HP/BP/Notch/Vol/Pan`), синхронизация к темпу (`1/16..4/1`).
- [ ] **String machine stereo chorus** (`http://jpcima.sdf1.org/lv2/string-machine-chorus-stereo`)
  - *Идея UI*: винтажная панель 3-фазного Solina/ARP Ensemble BBD-хоруса.

---

## 🌌 Приоритет 2 — Лучшие эффекты всех категорий

### Reverb
- [x] **Aether** (`zynthian_widget_aether.py`)
- [x] **Dragonfly Hall / Plate / Room Reverb** (`zynthian_widget_dragonfly_hall_reverb.py`, `zynthian_widget_dragonfly_plate_reverb.py`, `zynthian_widget_dragonfly_room_reverb.py`)
- [ ] **Tal-Reverb-III** — винтажный plate-реверб с крупными фейдерами `Wet/Dry/Room/Damp` и EQ.
- [ ] **Shiroverb** — шиммер-реверб с 2D-пэдом `Decay × Shimmer/Pitch`.

### Delay & Granular
- [x] **Argotlunar2** (`zynthian_widget_argotlunar2.py`)
- [ ] **Tal-Dub-3** — винтажный даб-дилей (2D-пэд `Cutoff × Resonance` в цепи обратной связи, `Drive`, `Sync`).
- [ ] **Modulay** — модулированный стерео-дилей с «плёночным» характером.
- [ ] **Regrader** — деградирующий лоу-фай дилей (биткраш + ресэмплинг в повторах).

### Simulator & Tape
- [ ] **CHOWTapeModel** — эмулятор катушечного магнитофона (вкладки `Tape/Hysteresis`, `Wow/Flutter`, `Loss/Degrade`, `Tone/Comp` + живая кривая гистерезиса).
- [ ] **x42 Whirl - Rotary Speaker** — эмуляция кабинета Leslie с крупным переключателем `Slow / Stop / Fast` (Brake), визуализацией вращения рупора и барабана.
- [ ] **Neural Amp Modeler (NAM) / AIDA-X** — минималистичная панель усилителя (`Input`, `EQ Low/Mid/High`, `Output`, `Gate`).

### Distortion & Saturation
- [ ] **ChowCentaur** — педаль Klon Centaur (`Gain`, `Treble`, `Output`, `Mode Trad/Neural`).
- [ ] **Temper** — современный фазовый дисторшн с визуализацией кривой искажения и `Cutoff/Reso`.
- [x] **Calf Saturator / Calf Crusher** (`zynthian_widget_calf_saturator.py`, `zynthian_widget_calf_crusher.py`)

### Filter, EQ, Dynamics & Pitch
- [ ] **Luftikus** — мастеринг-EQ в стиле Maag EQ4 с выделенной полосой **Air Band** (`2.5 / 5 / 10 / 20 / 40 kHz`).
- [ ] **x42-eq Stereo** — студийный параметрический EQ с интерактивной АЧХ и перетаскиваемыми точками полос.
- [ ] **x42-comp Stereo / Calf Sidechain Compressor** — компрессор с живой кривой `Threshold/Ratio/Knee` и индикатором GR.
- [ ] **Tal-Vocoder-II** — 11-полосный аналоговый вокодер с интерактивным 11-полосным графическим банком фильтров.

---

## 📋 Чек-лист перед реализацией каждого виджета (из `GEMINI.md`)
1. Проверить реальные ключи портов на Zynthian через `zynthian_lv2.get_plugin_ports(<plugin_url>)`.
2. Соблюсти единый дизайн (`COL_PANEL`, акценты вкладок, кнопки `≥ 34–44 px`, `gap = 6 px`, `UPDATE_PERIOD = 0.06`).
3. Реализовать двустороннюю привязку к 4 физическим энкодерам + `double-tap` сброс параметров.
4. Установить и проверить на Zynthian через `./install.sh`.
