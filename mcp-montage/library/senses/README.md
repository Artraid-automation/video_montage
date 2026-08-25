# Sense catalog (agent-authored)

**Not embeddings.** No OpenAI, no local sentence-transformers.

Карточки смыслов пишет агент (или автор) после разбора реального ролика: tags, situations, motion/broll hints. Поиск — **лексический** по этим полям (`pipeline/factory/senses.py`).

## Layout

```text
library/senses/
  catalog.json   # sense cards
  README.md
```

## When to add a card

- Accepted MOTION/BROLL brief that will recur
- Author names a situation in Gate review
- New vertical (still finance, health, …) after a completed project

## Link to B-roll

`search_catalog` may expand the query with tags from matching senses so empty lexical B-roll still gets useful tag overlap when assets appear later.
