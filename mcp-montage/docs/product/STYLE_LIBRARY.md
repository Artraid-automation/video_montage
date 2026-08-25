# Style library index

Searchable visual recipes. Machine source: `presets/styles/<version>/library.json`.  
Loader/search: `pipeline/factory/style_library.py`.  
Design: `docs/superpowers/specs/2026-07-20-dankoe-style-pack-design.md`.

## dankoe-mevga-v1 (Dan Koe Short)

Source: https://youtube.com/shorts/MeVGaMG28nc

| id | title | tags (grep) |
|----|-------|-------------|
| `captions_body` | Золотые фразовые субтитры | `#captions` `#serif` `#gold` `#chest-band` `#phrase` `#default-speech` `#talking-head` |
| `hook_title` | Крупный заголовок-хук | `#hook` `#title` `#serif` `#gold` `#cold-open` `#promise` `#thesis` `#big-text` |
| `framework_list` | Блюр + список-каркас | `#list` `#framework` `#steps` `#blur` `#darken` `#spotlight` `#enumerate` `#system` `#playbook` |
| `grade_talking_head` | База цветокора talking-head | `#grade` `#color` `#cinematic` `#talking-head` `#base-look` |

### Когда что брать (коротко)

- Обычная речь → `captions_body`
- Обещание / тезис / обложка мысли → `hook_title`
- 3+ шагов системы / playbook → `framework_list`
- Общий look камеры → `grade_talking_head` (`dankoe` grade)

Полные `what_happens` / `situations` / `anti_situations` — в JSON.
