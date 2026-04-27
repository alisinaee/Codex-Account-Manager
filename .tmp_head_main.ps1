$path='electron/src/main.js'
$lines=Get-Content $path
for($i=1;$i -le 28;$i++){"{0}: {1}" -f $i,$lines[$i-1]}
