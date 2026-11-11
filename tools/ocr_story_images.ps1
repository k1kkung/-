param(
    [Parameter(Mandatory = $true)]
    [string]$InputDirectory,
    [Parameter(Mandatory = $true)]
    [string]$OutputFile
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTaskGeneric = $null
foreach ($method in $methods) {
    if ($method.Name -ne "AsTask") {
        continue
    }
    $parameters = $method.GetParameters()
    if (
        $parameters.Length -eq 1 -and
        $parameters[0].ParameterType.Name -like "IAsyncOperation*"
    ) {
        $asTaskGeneric = $method
        break
    }
}
if ($null -eq $asTaskGeneric) {
    throw "Unable to locate the WindowsRuntime AsTask method."
}

function Await-Operation($Operation, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait(-1) | Out-Null
    return $task.Result
}

function Get-OcrText([string]$Path, $Engine) {
    $storageFile = Await-Operation `
        ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) `
        ([Windows.Storage.StorageFile])
    $stream = Await-Operation `
        ($storageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) `
        ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-Operation `
        ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) `
        ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-Operation `
        ($decoder.GetSoftwareBitmapAsync()) `
        ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await-Operation `
        ($Engine.RecognizeAsync($bitmap)) `
        ([Windows.Media.Ocr.OcrResult])

    $lines = foreach ($line in $result.Lines) {
        (($line.Words | ForEach-Object { $_.Text }) -join "")
    }
    return (($lines | Where-Object { $_.Trim() }) -join "`n")
}

function Get-StoryKey([string]$Name) {
    return [regex]::Replace(
        $Name,
        "^(.+?)_(\d+)_.*\.jpg(\.jpg)?$",
        '$1'
    )
}

function Get-PanelNumber([string]$Name) {
    $match = [regex]::Match(
        $Name,
        "^.+?_(\d+)_.*\.jpg(\.jpg)?$"
    )
    if ($match.Success) {
        return [int]$match.Groups[1].Value
    }
    return 999
}

function Get-TitleGuess([string]$Key) {
    $bookTitle = [regex]::Match(
        $Key,
        "\u300A([^\u300B]+)\u300B"
    )
    if ($bookTitle.Success) {
        return $bookTitle.Groups[1].Value
    }
    $dashTitle = [regex]::Match(
        $Key,
        "^[^-\u2014]*[-\u2014](?<title>[^-\u2014]+)$"
    )
    if ($dashTitle.Success) {
        return $dashTitle.Groups["title"].Value
    }
    return $Key
}

$inputPath = (Resolve-Path -LiteralPath $InputDirectory).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputFile)
$outputDirectory = Split-Path -Parent $outputPath
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$language = [Windows.Globalization.Language]::new("zh-Hans-CN")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) {
    throw "Windows Simplified Chinese OCR is not available."
}

$files = Get-ChildItem -LiteralPath $inputPath -File -Filter "*.jpg"
$groups = $files | Group-Object { Get-StoryKey $_.Name } | Sort-Object Name
$stories = @()
$index = 0

foreach ($group in $groups) {
    $index += 1
    $images = @()
    $orderedFiles = $group.Group | Sort-Object { Get-PanelNumber $_.Name }
    foreach ($file in $orderedFiles) {
        Write-Progress `
            -Activity "OCR story images" `
            -Status "$index/$($groups.Count): $($file.Name)" `
            -PercentComplete (($index - 1) / [Math]::Max(1, $groups.Count) * 100)
        $text = Get-OcrText $file.FullName $engine
        $images += [ordered]@{
            file = $file.Name
            panel = Get-PanelNumber $file.Name
            text = $text
        }
    }

    $stories += [ordered]@{
        key = $group.Name
        title_guess = Get-TitleGuess $group.Name
        image_count = $images.Count
        images = $images
    }
}

$payload = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    input_directory = $inputPath
    story_count = $stories.Count
    image_count = $files.Count
    stories = $stories
}

$json = $payload | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    $outputPath,
    $json,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Progress -Activity "OCR story images" -Completed
Write-Output "wrote $($stories.Count) stories from $($files.Count) images to $outputPath"
