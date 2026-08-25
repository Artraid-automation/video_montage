#!/bin/bash
# Детекция склеек: даунскейл до 270x480, порог сцены 0.25, вывод таймкодов
f="$1"; name=$(basename "$f" .mp4)
ffmpeg -v error -i "$f" -vf "scale=270:480,select='gt(scene,0.25)',metadata=print:file=-" -an -f null - 2>/dev/null \
 | grep -oP 'pts_time:\K[0-9.]+' > "analysis/${name}-cuts.txt"
echo "$name: $(wc -l < analysis/${name}-cuts.txt) склеек"
