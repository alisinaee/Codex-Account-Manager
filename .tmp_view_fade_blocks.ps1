$path='electron/src/styles/components.css'
$lines=Get-Content $path
for($i=1928;$i -le 1990;$i++){"{0}: {1}" -f $i,$lines[$i-1]}
for($i=2768;$i -le 2802;$i++){"{0}: {1}" -f $i,$lines[$i-1]}
