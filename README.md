# TagGUI

## Murf-Code fork: extra features

This fork of [TagGUI](https://github.com/jhc13/taggui) by jhc13 (based on v1.33.0) adds:

- **LM Studio and Ollama captioning.** Pick *LM Studio (local server)* or *Ollama (local server)* at the top of the Auto-Captioner model list to caption with whatever vision model you have loaded. Your prompt box is sent as the user prompt, with an editable system prompt, server URL, optional model name, max tokens, temperature and a Test Connection button. Reasoning (`<think>`) text is stripped out automatically.
- **Open File Location.** Right-click an image to show it in your file manager: Explorer with the file selected on Windows, Finder on macOS, and on Linux your desktop's file manager with the file selected (over D-Bus), or the folder opened with `xdg-open`.
- **Stackable tag filters.** Right-click a tag in All Tags or Image Tags and choose *Add to Filter*, *Exclude from Filter* or *Add to Filter (OR)* to build filters like `tag:"z4ush" AND NOT tag:"dog"`.
- **Better local-server captioning defaults.** New default tagging prompts, a *Max image size* setting (default 720 px on the longest side) for faster captions, and cleanup of semicolons, quotes and duplicate tags.
- **Mask files hidden.** OneTrainer/Fizgig mask images (`name-masklabel.png`, `-mask`, `_mask`) are skipped when loading a folder.
- **Remove tags from selected images.** With several images selected, deleting a tag in Image Tags (or right-click *Remove from Selected Images*, also in All Tags) removes it from every selected image that has it, after a confirmation that says how many images it affects. Undoable.
- **Crop tool (C).** Drag the edges or corners in the image viewer, then Enter or *Apply* to overwrite the image; Esc cancels. Crop mode closes after Apply or Cancel.
- **Remove brush (J).** Paint over something (red overlay; change the size with `[`/`]`, the mouse wheel, or by dragging left/right on the brush size box), right-click or right-drag to erase the mask, then Enter to fill it in with LaMa on the GPU (OpenCV fallback). Loops close and the hole grows slightly, as in PhotoCraft's Remove Tool.
- **Undo and redo (Ctrl+Z / Ctrl+Y).** One history covers tag edits and image edits, so Ctrl+Z brings back the image as it was before the last crop or removal and Ctrl+Y redoes it. Image edit history is kept in memory for the current session.
- **JTP-3 Hydra tagger.** RedRocket's e621 tagger (Apache-2.0) in the Auto-Captioner list, run locally on the GPU with the WD tagger settings (minimum score, maximum tags, tags to exclude). Uses an existing local copy (`TAGGUI_JTP3_DIR`, or `jtp-3-hydra` in the models folder below) or downloads it once.
- **Per-user models folder on every OS.** The big-lama and JTP-3 models are downloaded on first use to `%LOCALAPPDATA%\taggui\models` on Windows, `~/.local/share/taggui/models` on Linux (or `$XDG_DATA_HOME/taggui/models`), and `~/Library/Application Support/taggui/models` on macOS. Set `TAGGUI_MODELS_DIR` to use a different folder.

The Remove brush and JTP-3 tagger were built and tested on Windows with an NVIDIA GPU. They should work on Linux too, but haven't been tested there yet; please open an issue if something breaks.

<img src='images/icon.png' alt='TagGUI icon' width='128'>

Cross-platform desktop application for quickly adding and editing image tags
and captions, aimed towards creators of image datasets for generative AI
models.

<img src='images/screenshot-v1.25.0.png' alt='TagGUI screenshot' width='100%'>

## Features

- Keyboard-friendly interface for fast tagging
- Tag autocomplete based on your own most-used tags
- Integrated token counter (for Stable Diffusion)
- Automatic caption and tag generation with models including CogVLM, LLaVA, WD
  Tagger, and many more
- Batch tag operations for renaming, deleting, and sorting tags
- Advanced image list filtering

## Installation

**This fork has no prebuilt downloads. Run it from source as shown below.**
The releases page of the original TagGUI
(https://github.com/jhc13/taggui/releases) has the upstream version
*without* this fork's features, so don't install from there if you want them.

You need Git and Python 3.12 (3.11 should also work).
For GPU captioning, the Remove brush and the JTP-3 tagger, you also need an
NVIDIA GPU with a recent driver.
The LM Studio and Ollama options only need their local server running with a
vision model loaded.

### Linux

```bash
# Ubuntu/Debian packages (use your distro's equivalents elsewhere; on Ubuntu
# 22.04, python3.12 comes from the deadsnakes PPA).
# libxcb-cursor0 is needed by Qt; see https://stackoverflow.com/a/75941575
sudo apt install git python3.12 python3.12-venv python3.12-dev libxcb-cursor0

git clone -b lmstudio-ollama https://github.com/Murf-Code/taggui
cd taggui
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# On Linux, requirements.txt installs torch 2.6.0 from PyPI, which already
# includes CUDA 12.4 support. Check that it sees your NVIDIA GPU:
python -c "import torch; print(torch.cuda.is_available())"
# If that prints False, update your NVIDIA driver; if you need a different CUDA
# build, reinstall the same versions from the PyTorch index, for example:
#   pip install --force-reinstall torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

python taggui/run_gui.py
```

To start it again later: `cd taggui && source venv/bin/activate && python taggui/run_gui.py`.

`python3.12-dev` is only needed if you get an error while using a CogVLM2
model (see [this issue](https://github.com/jhc13/taggui/issues/234)).

### Windows

In Command Prompt or PowerShell, with [Git](https://git-scm.com/download/win)
and [Python 3.12](https://www.python.org/downloads/) installed:

```bat
git clone -b lmstudio-ollama https://github.com/Murf-Code/taggui
cd taggui
py -3.12 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

REM requirements.txt installs the CUDA 12.4 build of torch on Windows.
python -c "import torch; print(torch.cuda.is_available())"

python taggui\run_gui.py
```

(In PowerShell, activate with `venv\Scripts\Activate.ps1`.)

### macOS

The same steps as Linux work (install Python 3.12 from python.org or
Homebrew; no `apt` packages needed). Without an NVIDIA GPU, local models
and the Remove brush run on the CPU, which is much slower. This fork hasn't
been tested on macOS.

### Updating

From the `taggui` folder, with the venv activated:

```bash
git pull
pip install -r requirements.txt
```

## Usage

Load the directory containing your images by clicking the `Load Directory`
button in the center of the window (or `File` -> `Load Directory`).
Tags are loaded from `.txt` files in the directory with the same names as the
images.
Any changes you make to the tags are also automatically saved to these `.txt`
files.

## Automatic Captioning

<img src='images/auto-captioner-v1.18.0.png' alt='Auto-captioner screenshot' width='100%'>

In addition to manual tagging, you can automatically generate captions or tags
for your images inside TagGUI.
GPU generation requires a compatible NVIDIA GPU, and CPU generation is also
supported.

To use the feature, select the images you want to caption in the image list,
then select the captioning model you want to use in the Auto-Captioner pane.
If you have a local directory containing previously downloaded models, you can
set it in `File` -> `Settings` to include the models in the model list.
Click the `Start Auto-Captioning` button to start captioning.
You can select multiple images to batch generate captions for all of them.
It can take up to several minutes to download and load a model when you first
use it, but subsequent generations will be much faster.

### Captioning parameters

`Prompt`: Instructions given to the captioning model.
Prompt formats are handled automatically based on the selected model.
You can use the following template variables to dynamically insert information
about each image into the prompt:

- `{tags}`: The tags of the image, separated by commas.
- `{name}`: The file name of the image without the extension.
- `{directory}` or `{folder}`: The name of the directory containing the image.

An example prompt using a template variable could be
`Describe the image using the following tags as context: {tags}`.
With this prompt, `{tags}` would be replaced with the existing tags of each
image before the prompt is sent to the model.

`Start caption with`: Generated captions will start with this text.

`Remove tag separators in caption`: If checked, tag separators (commas by
default) will be removed from the generated captions.

`Discourage from caption`: Words or phrases that should not be present in the
generated captions.
You can separate multiple words or phrases with commas (`,`).
For example, you can put `appears,seems,possibly` to prevent the model from
using an uncertain tone in the captions.
The words may still be generated due to limitations related to tokenization.

`Include in caption`: Words or phrases that should be present somewhere in the
generated captions.
You can separate multiple words or phrases with commas (`,`).
You can also allow the captioning model to choose from a group of words or
phrases by separating them with `|`.
For example, if you put `cat,orange|white|black`, the model will attempt to
generate captions that contain the word `cat` and either `orange`, `white`,
or `black`.
It is not guaranteed that all of your specifications will be met.

`Tags to exclude` (WD Tagger models): Tags that should not be generated,
separated by commas.

Many of the other generation parameters are described in the
[Hugging Face documentation](https://huggingface.co/docs/transformers/main/en/main_classes/text_generation#transformers.GenerationConfig).

## Advanced Image List Filtering

The basic functionality of filtering for images that contain a certain tag is
available by clicking on the tag in the `All Tags` pane.
In addition to this, you can construct more complex filters in
the `Filter Images` box at the top of the `Images` pane.

<details>
<summary>
Click here to see the full documentation for the filter syntax.
</summary>

### Filter criteria

These are the prefixes you can use to specify the filter criteria you want to
apply:

- `tag:`: Images that have the filter term as a tag
    - `tag:cat` will match images with the tag `cat`.
- `caption`: Images that contain the filter term in the caption
    - The caption is the list of tags as a single string, as it appears in the
      `.txt` file.
    - `caption:cat` will match images that have `cat` anywhere in the
      caption. For example, images with the tag `orange cat` or the
      tag `catastrophe`.
- `name`: Images that contain the filter term in the file name
    - `name:cat` will match images such as `cat-1.jpg` or `large_cat.png`.
- `path`: Images that contain the filter term in the full file path
    - `path:cat` will match images such as `C:\Users\cats\dog.jpg` or
      `/home/dogs/cat.jpg`.
- You can also use a filter term with no prefix to filter for images that
  contain the term in either the caption or the file path.
    - `cat` will match images containing `cat` in the caption or file path.

The following are prefixes for numeric filters. The operators `=` (`==` also
works), `!=`, `<`, `>`, `<=`, and `>=` are used to specify the type of
comparison.

- `tags`: Images that have the specified number of tags
    - `tags:=13` will match images that have exactly 13 tags.
    - `tags:!=7` will match images that do not have exactly 7 tags (images with
      less than 7 tags or more than 7 tags).
- `chars`: Images that have the specified number of characters in the caption
    - `chars:<100` will match images that have less than 100 characters in the
      caption.
    - `chars:>=30` will match images that have 30 or more characters in the
      caption.
- `tokens`: Images that have the specified number of tokens in the caption
    - `tokens:>75` will match images that have more than 75 tokens in the
      caption.
    - `tokens:<=50` will match images that have 50 or fewer tokens in the
      caption.

### Spaces and quotes

If the filter term contains spaces, you must enclose it in quotes (either
single or double quotes).
For example, to find images with the tag `orange cat`, you must
use `tag:"orange cat"` or `tag:'orange cat'`.
If you have both spaces and quotes in the filter term, you can escape the
quotes with backslashes.
For example, you can use `tag:"orange \"cat\""` for the tag `orange "cat"`.
An alternative is to use different types of quotes for the outer and inner
quotes, like so: `tag:'orange "cat"'`.

### Wildcards

You can use the `*` character as a wildcard to match any number of any
characters, and the `?` character to match any single character.
For example, `tag:*cat` will match images with tags like `orange cat`,
`large cat`, and `cat`.

### Combining filters

Logical operators can be used to combine multiple filters:

- `NOT`: Images that do not match the filter
    - `NOT tag:cat` will match images that do not have the tag `cat`.
- `AND`: Images that match both filters before and after the operator
    - `tag:cat AND tag:orange` will match images that have both the tag `cat`
      and the tag `orange`.
- `OR`: Images that match either filter before or after the operator
    - `tag:cat OR tag:dog` will match images that have either the tag `cat` or
      the tag `dog`, or both.

The lowercase versions of these operators will also work: `not`, `and`,
and `or`.

The operator precedence is `NOT` > `AND` > `OR`, so by default, `NOT` will be
evaluated first, then `AND`, then `OR`.
You can use parentheses to change this order.
For example, in `tag:cat AND (tag:orange OR tag:white)`, the `OR` will be
evaluated first, matching images that have the tag `cat` and either the
tag `orange` or the tag `white`.
You can nest parentheses and operators to create arbitrarily complex filters.
</details>

## Controls

- ⭐ Previous / next image: `Ctrl`+`Up` / `Down` (just `Up` / `Down` also works
  in some cases)
- Jump to the first untagged image: `Ctrl`+`J`
- Focus the `Filter Images` box: `Alt`+`F`
- Focus the `Add Tag` box: `Alt`+`A`
- Focus the `Image Tags` list: `Alt`+`I`
- Focus the `Search Tags` box: `Alt`+`S`
- Focus the `Start Auto-Captioning` button: `Alt`+`C`

### Images pane

- First / last image: `Home` / `End`
- Select multiple images: Hold `Ctrl` or `Shift` and click the images
- Select all images: `Ctrl`+`A`
- Invert selection: `Ctrl`+`I`
- Right-clicking on an image will bring up the context menu, which includes
  actions such as copying and pasting tags and moving or copying selected
  images to another directory.

### Image Tags pane

- Add a tag: Type the tag into the `Add Tag` box and press `Enter`
- ⭐ Add the first tag suggested by autocomplete: `Ctrl`+`Enter`
- Add a tag to multiple images: Select the images in the image list add
  the tag
- Delete a tag: Select the tag and press `Delete`
- Rename a tag: Double-click the tag, or select the tag and press `F2`
- Reorder tags: Drag and drop the tags
- Select multiple tags: Hold `Ctrl` or `Shift` and click the tags

### All Tags pane

- Show all images containing a tag: Select the tag (When `Tag click action` is
  set to `Filter images for tag`)
- Add a tag to selected images: Click the tag (When `Tag click action` is set
  to `Add tag to selected images`)
- Delete all instances of a tag: Select the tag and press `Delete`
- Rename all instances of a tag: Double-click the tag, or select the tag and
  press `F2`

The `Edit` menu contains additional features for batch tag operations, such as
`Find and Replace` (`Ctrl`+`R`) and `Batch Reorder Tags` (`Ctrl`+`B`).
