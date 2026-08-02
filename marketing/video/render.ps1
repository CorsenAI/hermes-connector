[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$OutputDir = $PSScriptRoot
$BuildDir = Join-Path $OutputDir '.build'
$QaDir = Join-Path $OutputDir 'qa'
$Ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$Ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source

$EncoderList = (& $Ffmpeg -hide_banner -encoders 2>&1 | Out-String)
$UseNvenc = $EncoderList -match '\bh264_nvenc\b'
if ($UseNvenc) {
    Write-Host 'Using NVIDIA NVENC for H.264 output (h264_nvenc).'
    $IntermediateVideoArgs = @('-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '15', '-b:v', '0', '-pix_fmt', 'yuv420p')
    $FinalVideoArgs = @('-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq', '-rc', 'vbr', '-cq', '17', '-b:v', '0', '-spatial-aq', '1', '-aq-strength', '8', '-pix_fmt', 'yuv420p')
}
else {
    Write-Warning 'h264_nvenc is unavailable; falling back to libx264.'
    $IntermediateVideoArgs = @('-c:v', 'libx264', '-preset', 'medium', '-crf', '15', '-pix_fmt', 'yuv420p')
    $FinalVideoArgs = @('-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p')
}

$Marquee = Join-Path $ProjectRoot 'store\promo-marquee-1400x560.png'
$Product = Join-Path $ProjectRoot 'store\screenshot-product-1280x800.png'

foreach ($RequiredFile in @($Marquee, $Product)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Missing source asset: $RequiredFile"
    }
}

New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
New-Item -ItemType Directory -Path $QaDir -Force | Out-Null

function Invoke-FFmpeg {
    param([Parameter(Mandatory)][string[]]$CommandArgs)
    & $Ffmpeg @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg failed with exit code $LASTEXITCODE"
    }
}

function Render-StillSegment {
    param(
        [Parameter(Mandatory)][string[]]$Inputs,
        [Parameter(Mandatory)][string]$Filter,
        [Parameter(Mandatory)][double]$Duration,
        [Parameter(Mandatory)][string]$Output
    )

    $InputArgs = @()
    foreach ($InputPath in $Inputs) {
        $InputArgs += @('-loop', '1', '-framerate', '30', '-i', $InputPath)
    }

    Invoke-FFmpeg (@(
        '-y', '-hide_banner', '-loglevel', 'warning'
    ) + $InputArgs + @(
        '-t', $Duration.ToString([Globalization.CultureInfo]::InvariantCulture),
        '-filter_complex', $Filter,
        '-map', '[v]',
        '-r', '30',
        '-an'
    ) + $IntermediateVideoArgs + @(
        $Output
    ))
}

Push-Location $OutputDir
try {
    $Segments = 1..7 | ForEach-Object { Join-Path $BuildDir ("segment-{0:d2}.mp4" -f $_) }

    Render-StillSegment -Inputs @($Marquee) -Duration 5.5 -Output $Segments[0] -Filter @'
[0:v]split=2[bg][fg];
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=35,eq=brightness=-0.34:saturation=1.22[bg2];
[fg]scale=1800:-2[fg2];
[bg2][fg2]overlay=(W-w)/2:(H-h)/2,zoompan=z='min(zoom+0.00032,1.035)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,fade=t=in:st=0:d=0.4,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Product) -Duration 6.0 -Output $Segments[1] -Filter @'
[0:v]split=2[bg][fg];
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=32,eq=brightness=-0.38:saturation=1.10[bg2];
[fg]scale=-2:1040[fg2];
[bg2][fg2]overlay=(W-w)/2:(H-h)/2,drawbox=x=124:y=14:w=1672:h=1052:color=0x20dfff@0.22:t=3,zoompan=z='min(zoom+0.00020,1.022)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Product) -Duration 6.0 -Output $Segments[2] -Filter @'
[0:v]split=2[bg][panel];
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=38,eq=brightness=-0.50:saturation=1.18[bg2];
[panel]crop=390:720:890:80,scale=-2:1000[panel2];
[bg2][panel2]overlay=1328:40,drawbox=x=1318:y=30:w=574:h=1020:color=0x20dfff@0.65:t=4,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Product) -Duration 6.0 -Output $Segments[3] -Filter @'
[0:v]split=2[bg][fg];
[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=32,eq=brightness=-0.42:saturation=1.12[bg2];
[fg]scale=-2:1040[fg2];
[bg2][fg2]overlay=(W-w)/2:(H-h)/2,drawbox=x=1320:y=138:w=500:h=350:color=0x20dfff@0.78:t=5,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Product) -Duration 6.0 -Output $Segments[4] -Filter @'
[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=7,eq=brightness=-0.56:saturation=1.15,zoompan=z='min(zoom+0.00022,1.024)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Marquee) -Duration 6.0 -Output $Segments[5] -Filter @'
[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=18,eq=brightness=-0.48:saturation=1.28,zoompan=z='min(zoom+0.00025,1.027)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p[v]
'@

    Render-StillSegment -Inputs @($Marquee) -Duration 6.0 -Output $Segments[6] -Filter @'
[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=12,eq=brightness=-0.62:saturation=1.12,drawbox=x=0:y=0:w=iw:h=ih:color=black@0.38:t=fill,zoompan=z='min(zoom+0.00028,1.030)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,format=yuv420p[v]
'@

    $Montage = Join-Path $BuildDir 'base-horizontal.mp4'
    $InputArgs = @()
    foreach ($Segment in $Segments) {
        $InputArgs += @('-i', $Segment)
    }
    $Xfade = @'
[0:v][1:v]xfade=transition=fade:duration=0.5:offset=5.0[x1];
[x1][2:v]xfade=transition=fade:duration=0.5:offset=10.5[x2];
[x2][3:v]xfade=transition=fade:duration=0.5:offset=16.0[x3];
[x3][4:v]xfade=transition=fade:duration=0.5:offset=21.5[x4];
[x4][5:v]xfade=transition=fade:duration=0.5:offset=27.0[x5];
[x5][6:v]xfade=transition=fade:duration=0.5:offset=32.5,fps=30,format=yuv420p[v]
'@
    Invoke-FFmpeg (@('-y', '-hide_banner', '-loglevel', 'warning') + $InputArgs + @(
        '-filter_complex', $Xfade,
        '-map', '[v]',
        '-an'
    ) + $IntermediateVideoArgs + @(
        $Montage
    ))

    $SynthAudio = "aevalsrc=0.018*sin(2*PI*55*t)*(0.75+0.25*sin(2*PI*0.12*t))+0.009*sin(2*PI*82.41*t)*(0.70+0.30*sin(2*PI*0.08*t))+0.004*sin(2*PI*220*t):s=48000:d=38.5"
    $Horizontal = Join-Path $OutputDir 'hermes-connector-promo-1080p.mp4'
    Invoke-FFmpeg (@(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', $Montage,
        '-f', 'lavfi', '-i', $SynthAudio,
        '-filter_complex', "[0:v]ass=overlay-horizontal.ass[v];[1:a]afade=t=in:st=0:d=1.2,afade=t=out:st=37.0:d=1.5,lowpass=f=1600,volume=5.0[a]",
        '-map', '[v]', '-map', '[a]',
        '-t', '38.5',
        '-profile:v', 'high', '-level:v', '4.1'
    ) + $FinalVideoArgs + @(
        '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
        '-movflags', '+faststart',
        $Horizontal
    ))

    $VerticalBase = Join-Path $BuildDir 'base-vertical.mp4'
    Invoke-FFmpeg (@(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', $Montage,
        '-filter_complex', "[0:v]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=38,eq=brightness=-0.38:saturation=1.16[bg2];[fg]scale=1000:-2[fg2];[bg2][fg2]overlay=(W-w)/2:(H-h)/2,drawbox=x=36:y=665:w=1008:h=590:color=0x20dfff@0.20:t=3,format=yuv420p[v]",
        '-map', '[v]', '-an'
    ) + $IntermediateVideoArgs + @(
        $VerticalBase
    ))

    $Vertical = Join-Path $OutputDir 'hermes-connector-promo-vertical.mp4'
    Invoke-FFmpeg (@(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', $VerticalBase,
        '-f', 'lavfi', '-i', $SynthAudio,
        '-filter_complex', "[0:v]ass=overlay-vertical.ass[v];[1:a]afade=t=in:st=0:d=1.2,afade=t=out:st=37.0:d=1.5,lowpass=f=1600,volume=5.0[a]",
        '-map', '[v]', '-map', '[a]',
        '-t', '38.5',
        '-profile:v', 'high', '-level:v', '4.2'
    ) + $FinalVideoArgs + @(
        '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
        '-movflags', '+faststart',
        $Vertical
    ))

    $Thumbnail = Join-Path $OutputDir 'hermes-connector-thumbnail-1280x720.png'
    Invoke-FFmpeg @(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', $Marquee, '-i', $Product,
        '-filter_complex', "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,gblur=sigma=25,eq=brightness=-0.38:saturation=1.24[bg];[1:v]crop=390:720:890:80,scale=-2:620[panel];[bg][panel]overlay=940:50,drawbox=x=930:y=40:w=350:h=640:color=0x20dfff@0.72:t=4,ass=thumbnail.ass,format=rgb24[v]",
        '-map', '[v]', '-frames:v', '1', '-update', '1',
        $Thumbnail
    )

    $Palette = Join-Path $BuildDir 'gif-palette.png'
    $Gif = Join-Path $OutputDir 'hermes-connector-demo.gif'
    Invoke-FFmpeg @(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', '16.7', '-t', '7.0', '-i', $Horizontal,
        '-vf', 'fps=12,scale=960:-1:flags=lanczos,palettegen=max_colors=160:stats_mode=diff',
        '-frames:v', '1', '-update', '1',
        $Palette
    )
    Invoke-FFmpeg @(
        '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', '16.7', '-t', '7.0', '-i', $Horizontal,
        '-i', $Palette,
        '-filter_complex', '[0:v]fps=12,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle[v]',
        '-map', '[v]', '-an', '-loop', '0',
        $Gif
    )

    if ((Get-Item -LiteralPath $Gif).Length -gt 8MB) {
        Invoke-FFmpeg @(
            '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', '16.7', '-t', '6.5', '-i', $Horizontal,
            '-vf', 'fps=10,scale=860:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff',
            '-frames:v', '1', '-update', '1',
            $Palette
        )
        Invoke-FFmpeg @(
            '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', '16.7', '-t', '6.5', '-i', $Horizontal,
            '-i', $Palette,
            '-filter_complex', '[0:v]fps=10,scale=860:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle[v]',
            '-map', '[v]', '-an', '-loop', '0',
            $Gif
        )
    }

    foreach ($Frame in @(
        @{ Time = '1.5'; Name = 'qa-01-hero.png' },
        @{ Time = '12.5'; Name = 'qa-02-product.png' },
        @{ Time = '24.0'; Name = 'qa-03-actions.png' },
        @{ Time = '36.0'; Name = 'qa-04-cta.png' }
    )) {
        Invoke-FFmpeg @(
            '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', $Frame.Time, '-i', $Horizontal,
            '-frames:v', '1', '-update', '1',
            (Join-Path $QaDir $Frame.Name)
        )
    }

    foreach ($Frame in @(
        @{ Time = '1.5'; Name = 'qa-vertical-01-hero.png' },
        @{ Time = '12.5'; Name = 'qa-vertical-02-product.png' },
        @{ Time = '24.0'; Name = 'qa-vertical-03-actions.png' },
        @{ Time = '36.0'; Name = 'qa-vertical-04-cta.png' }
    )) {
        Invoke-FFmpeg @(
            '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', $Frame.Time, '-i', $Vertical,
            '-frames:v', '1', '-update', '1',
            (Join-Path $QaDir $Frame.Name)
        )
    }

    Write-Host "`nHorizontal video"
    & $Ffprobe -v error -show_entries format=duration,size -show_entries stream=index,codec_name,width,height,r_frame_rate,pix_fmt -of json $Horizontal
    Write-Host "`nVertical video"
    & $Ffprobe -v error -show_entries format=duration,size -show_entries stream=index,codec_name,width,height,r_frame_rate,pix_fmt -of json $Vertical
    Write-Host "`nGIF size: $([math]::Round((Get-Item -LiteralPath $Gif).Length / 1MB, 2)) MiB"
}
finally {
    Pop-Location
}
