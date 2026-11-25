# Zynthian UI Patches / Патчи для Zynthian UI

Optional patches for `/zynthian/zynthian-ui` on Zynthian that complement custom widgets in `widgets_user/`.  
Опциональные патчи для `/zynthian/zynthian-ui` на Zynthian, дополняющие кастомные виджеты из `widgets_user/`.

---

## Patches / Список патчей

| Patch | Target in `zynthian-ui` | Description / Описание |
| --- | --- | --- |
| [`01-highlight-custom-widgets-in-menu.patch`](01-highlight-custom-widgets-in-menu.patch) | `zyngui/zynthian_gui_engine.py` | **EN:** Marks engines/FX that have a widget in `zyngui/widgets_user/` with a `◆ ` prefix and `#4dabf7` blue color in the engine menu.<br>**RU:** Помечает плагины/синты с виджетом в `zyngui/widgets_user/` префиксом `◆ ` и голубым цветом (`#4dabf7`) в списке выбора движков. |
| [`02-prioritize-custom-gui-widget.patch`](02-prioritize-custom-gui-widget.patch) | `zyngui/zynthian_gui_control.py` | **EN:** Gives `processor.engine.custom_gui_fpath` priority over built-in `screen_type` (`filter`/`envelope`) mini-widgets.<br>**RU:** Даёт `processor.engine.custom_gui_fpath` приоритет над встроенными мини-виджетами (`filter`/`envelope`). |
| [`03-zynaddsubfx-custom-widget.patch`](03-zynaddsubfx-custom-widget.patch) | `zyngine/zynthian_engine_zynaddsubfx.py` | **EN:** Loads `widgets_user/zynthian_widget_zynaddsubfx.py` and removes `filter` tags from `filter cutoff`/`filter resonance`.<br>**RU:** Подключает `widgets_user/zynthian_widget_zynaddsubfx.py` и убирает теги `filter` с `filter cutoff`/`filter resonance`. |

---

## Usage / Использование

```bash
# Check patch status on Zynthian (default: root@10.0.99.99)
# Проверить статус патчей на Zynthian (по умолчанию: root@10.0.99.99)
./patches/apply_patches.sh --check

# Apply all patches (idempotent — already applied patches are skipped)
# Применить все патчи (идемпотентно — уже применённые пропускаются)
./patches/apply_patches.sh

# Revert all patches (e.g. before updating Zynthian)
# Откатить все патчи (например, перед обновлением Zynthian)
./patches/apply_patches.sh --revert

# Specify a custom host / Указать другой хост
./patches/apply_patches.sh root@<zynthian-ip>
```

Restart Zynthian UI after applying or reverting / После применения или отката перезапустите UI:

```bash
ssh root@10.0.99.99 systemctl restart zynthian
```
