for f in *.mkv; do
  echo "====================" >>ffprobe_report.txt
  echo "$f" >>ffprobe_report.txt
  echo "====================" >>ffprobe_report.txt
  ffprobe "$f" >>ffprobe_report.txt 2>&1
done
