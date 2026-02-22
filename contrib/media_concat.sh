# combine all mp4s in current directory (assuming they are in ls order) to a combined one

ffmpeg -f concat -safe 0 -i <(for f in ./*.mp4; do echo "file '$PWD/$f'"; done) -c copy combined.mp4
