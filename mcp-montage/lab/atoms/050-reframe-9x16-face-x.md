# ATOM: reframe 9:16 with face X

Status: proven
Last run: 2026-07-16

## Цель

1280x720 landscape → 1080x1920, лицо в кадре.

## Шаги

1. Найти median X skin-tone пикселей на sample frame
2. `scale=-2:1920,crop=1080:1920:CROP_X:0`
3. `CROP_X = face_x * (1920/720) - 540` (clamp to [0, scaled_w-1080])

## Фейл

Geometric center crop на этом исходнике попал в торс — не использовать вслепую.
