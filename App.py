import io
import json
import logging
import os
import secrets
import threading
import warnings
import zipfile

import pymupdf as fitz
import uvicorn
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response


# ===================== SETTINGS =====================

app = FastAPI(
    title="Document Studio",
    docs_url=None,
    redoc_url=None,
)

MAX_UPLOAD = 40 * 1024 * 1024
MAX_OUTPUT = 60 * 1024 * 1024
MAX_PAGES = 500
MAX_PIXELS = 20_000_000

# One document-processing job at a time within this process.
PROCESS_LOCK = threading.Lock()

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.simplefilter("error", Image.DecompressionBombWarning)


# ===================== FRONTEND =====================

HTML = r"""
<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b1020">
<title>Document Studio | PDF & Image Tools</title>
<style>
:root{
  --bg:#0b1020;--card:#141d33;--border:#293753;
  --text:#edf2ff;--muted:#9eacc7;--accent:#8179ff;
}
*{box-sizing:border-box}
body{
  margin:0;font:16px/1.6 system-ui,sans-serif;
  background:var(--bg);color:var(--text)
}
header{
  border-bottom:1px solid var(--border);
  padding:18px 22px;background:#0e1528;
}
.nav{
  max-width:1120px;margin:auto;display:flex;
  justify-content:space-between;align-items:center;gap:15px
}
.brand{font-size:23px;font-weight:850;letter-spacing:-.5px}
.badge{
  font-size:12px;background:#133a32;color:#a5f2d1;
  padding:6px 12px;border-radius:25px
}
main{max-width:1160px;padding:34px 20px;margin:auto}
.hero{padding:16px 0 25px}
.eyebrow{font-size:12px;letter-spacing:2px;color:#b9b2ff}
h1{
  font-size:clamp(34px,6vw,58px);line-height:1.12;
  letter-spacing:-2px;margin:14px 0
}
h1 span{color:#a29aff}
p{color:var(--muted)}
.search{
  max-width:540px;margin-top:24px;
}
input,select{
  width:100%;background:#0b1426;color:var(--text);
  border:1px solid var(--border);border-radius:11px;
  padding:13px;font:inherit
}
input:focus,select:focus{outline:2px solid var(--accent)}
.grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));
  gap:14px;margin:12px 0 30px
}
.tool{
  text-align:left;padding:20px;border-radius:16px;
  background:var(--card);color:var(--text);
  border:1px solid var(--border);cursor:pointer;
  transition:transform .15s,border-color .15s
}
.tool:hover,.tool.active{
  border-color:var(--accent);transform:translateY(-2px)
}
.icon{font-size:25px;display:block;margin-bottom:9px}
.tool strong{font-size:17px;display:block}
.tool small{color:var(--muted);display:block;margin-top:6px}
.panel{
  background:var(--card);border:1px solid var(--border);
  border-radius:20px;padding:25px
}
h2{margin:0;font-size:25px}
label{display:block;font-size:14px;margin:16px 0 7px}
input[type=file]{
  padding:26px 15px;border:2px dashed #46577c;
  cursor:pointer
}
.btn,.download{
  display:inline-block;background:var(--accent);
  color:#fff;border:0;border-radius:11px;
  padding:14px 22px;font-size:15px;font-weight:750;
  cursor:pointer;text-decoration:none;margin-top:20px
}
button:disabled{opacity:.55;cursor:wait}
.small{font-size:13px;color:var(--muted)}
#fileList{overflow-wrap:anywhere;margin-top:10px}
#status{margin-top:18px;white-space:pre-wrap;overflow-wrap:anywhere}
.error{color:#ffaaaa}
.success{color:#a3edc7}
.notice{
  margin-top:22px;padding:14px;border-radius:10px;
  background:#0c1427;font-size:13px;color:var(--muted)
}
footer{
  padding:30px 20px;text-align:center;
  color:var(--muted);font-size:13px
}
[hidden]{display:none!important}
@media(max-width:500px){
  .nav{flex-wrap:wrap}
  .grid{grid-template-columns:1fr 1fr;gap:10px}
  .tool{padding:14px}
  .tool strong{font-size:15px}
  .panel{padding:18px}
}
</style>
</head>
<body>
<header>
  <div class="nav">
    <div class="brand">◈ Document Studio</div>
    <div class="badge">13 PDF & Image Tools</div>
  </div>
</header>

<main>
  <section class="hero">
    <div class="eyebrow">YOUR EVERYDAY DOCUMENT WORKSPACE</div>
    <h1>PDF aur Images.<br><span>Kaam ab easy.</span></h1>
    <p>Merge, rotate, protect, convert aur resize — ek jagah.</p>
    <input id="search" class="search"
      placeholder="Search tools..." aria-label="Search tools">
  </section>

  <section id="tools" class="grid" aria-label="Available tools"></section>

  <section id="workspace" class="panel">
    <h2 id="title"></h2>
    <p id="description"></p>

    <form id="form">
      <label for="files">File select karein</label>
      <input type="file" id="files" required>
      <div id="fileList" class="small"></div>

      <div id="passwordBox">
        <label for="inputPassword">
          Existing PDF password — encrypted PDF ke liye
        </label>
        <input id="inputPassword" type="password" autocomplete="off">
      </div>

      <div id="options"></div>

      <button id="submit" class="btn" type="submit">
        Process File
      </button>
    </form>

    <div id="status" role="status" aria-live="polite"></div>
    <a id="download" class="download" hidden>Download Result</a>

    <div class="notice">
      Maximum 20 files aur 40 MB total upload.
      Files processing ke liye is website ke server par upload hoti hain.
      App permanent copies save nahi karta; temporary upload files request
      ke baad close ki jaati hain. Hosting-level retention alag ho sakti hai.
      PDF modification digital signatures ko invalidate kar sakti hai.
    </div>
  </section>
</main>

<footer>
  Independent toolkit. Pi7 ya Sejda se affiliated nahi hai.
</footer>

<script>
const $ = id => document.getElementById(id);

const tools = [
  {
    id:"merge",icon:"📚",name:"Merge PDF",
    desc:"Multiple PDFs ko file-list order mein combine karein.",
    multiple:true,pdf:true
  },
  {
    id:"extract",icon:"✂️",name:"Extract Pages",
    desc:"Selected PDF pages se ek naya PDF banayein.",
    pdf:true,
    fields:[
      {name:"pages",label:"Pages / ranges",value:"1",placeholder:"1-3,5,8"}
    ]
  },
  {
    id:"rotate",icon:"🔄",name:"Rotate PDF",
    desc:"PDF pages rotate karein. Blank pages field = all pages.",
    pdf:true,
    fields:[
      {name:"pages",label:"Pages / ranges — optional"},
      {name:"angle",label:"Rotation",choices:["90","180","270"]}
    ]
  },
  {
    id:"compress",icon:"📦",name:"Compress PDF",
    desc:"Basic lossless compression. Size reduction guaranteed nahi.",
    pdf:true
  },
  {
    id:"lock",icon:"🔒",name:"Protect PDF",
    desc:"PDF par AES-256 password encryption lagayein.",
    pdf:true,
    fields:[
      {name:"password",label:"New PDF password",type:"password",required:true}
    ]
  },
  {
    id:"unlock",icon:"🔓",name:"Unlock PDF",
    desc:"Correct existing password ke saath unencrypted copy banayein.",
    pdf:true
  },
  {
    id:"images-to-pdf",icon:"🖼️",name:"Images to PDF",
    desc:"JPG, PNG aur WebP images ko A4 PDF mein combine karein.",
    multiple:true
  },
  {
    id:"pdf-to-images",icon:"🎞️",name:"PDF to Images",
    desc:"PDF pages ki PNG images ZIP mein download karein.",
    pdf:true,
    fields:[
      {name:"pages",label:"Pages / ranges — optional"},
      {name:"dpi",label:"Resolution",choices:["96","120","144"]}
    ]
  },
  {
    id:"pdf-to-text",icon:"📝",name:"PDF to Text",
    desc:"Selectable text extract karein. Scanned PDFs ka OCR included nahi.",
    pdf:true
  },
  {
    id:"watermark",icon:"💧",name:"Watermark PDF",
    desc:"Har PDF page par light English-text watermark add karein.",
    pdf:true,
    fields:[
      {name:"text",label:"Watermark text",value:"CONFIDENTIAL",required:true}
    ]
  },
  {
    id:"numbers",icon:"🔢",name:"Page Numbers",
    desc:"PDF pages ke bottom par numbering add karein.",
    pdf:true
  },
  {
    id:"image-convert",icon:"🎨",name:"Convert Image",
    desc:"JPG, PNG aur WebP formats ke beech conversion.",
    fields:[
      {name:"format",label:"Output format",choices:["png","jpg","webp"]}
    ]
  },
  {
    id:"image-resize",icon:"📐",name:"Resize Image",
    desc:"Aspect ratio preserve karke selected size ke andar fit karein.",
    fields:[
      {name:"width",label:"Maximum width (px)",type:"number",value:1200},
      {name:"height",label:"Maximum height (px)",type:"number",value:1200},
      {name:"format",label:"Output format",choices:["png","jpg","webp"]}
    ]
  }
];

let current;
let resultURL = null;
let busy = false;

function resetResult(){
  if(resultURL) URL.revokeObjectURL(resultURL);
  resultURL = null;
  $("download").hidden = true;
  $("status").textContent = "";
  $("status").className = "";
}

function selectTool(tool){
  if(busy) return;
  current = tool;
  resetResult();
  $("form").reset();
  $("fileList").textContent = "";
  $("title").textContent = tool.name;
  $("description").textContent = tool.desc;
  $("files").multiple = !!tool.multiple;
  $("files").accept = tool.pdf ? ".pdf" : ".jpg,.jpeg,.png,.webp";
  $("passwordBox").hidden = !tool.pdf;
  $("options").replaceChildren();

  for(const field of tool.fields || []){
    const label = document.createElement("label");
    label.textContent = field.label;
    label.htmlFor = "option-" + field.name;

    const input = document.createElement(field.choices ? "select" : "input");
    input.id = "option-" + field.name;
    input.name = field.name;
    input.required = !!field.required;

    if(field.choices){
      for(const value of field.choices){
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        input.append(option);
      }
    }else{
      input.type = field.type || "text";
      input.value = field.value ?? "";
      input.placeholder = field.placeholder || "";
      if(input.type === "number"){
        input.min = "1";
        input.max = "8000";
      }
    }
    $("options").append(label,input);
  }

  document.querySelectorAll(".tool").forEach(button=>{
    button.classList.toggle("active",button.dataset.id === tool.id);
  });
}

for(const tool of tools){
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tool";
  button.dataset.id = tool.id;
  button.dataset.search = (tool.name + " " + tool.desc).toLowerCase();

  const icon = document.createElement("span");
  icon.className = "icon";
  icon.textContent = tool.icon;

  const name = document.createElement("strong");
  name.textContent = tool.name;

  const desc = document.createElement("small");
  desc.textContent = tool.desc;

  button.append(icon,name,desc);
  button.onclick = ()=>selectTool(tool);
  $("tools").append(button);
}

$("search").oninput = ()=>{
  const query = $("search").value.trim().toLowerCase();
  document.querySelectorAll(".tool").forEach(button=>{
    button.hidden = !button.dataset.search.includes(query);
  });
};

$("files").onchange = ()=>{
  $("fileList").textContent = Array.from($("files").files)
    .map((file,index)=>
      `${index+1}. ${file.name} (${(file.size/1048576).toFixed(2)} MB)`
    ).join(" • ");
};

$("form").onsubmit = async event=>{
  event.preventDefault();
  if(busy) return;
  resetResult();

  const files = Array.from($("files").files);
  const size = files.reduce((sum,file)=>sum+file.size,0);

  if(!files.length || files.length>20 || size>40*1048576){
    $("status").textContent = "1–20 files aur maximum 40 MB total allowed.";
    $("status").className = "error";
    return;
  }

  const options = {input_password:$("inputPassword").value};
  $("options").querySelectorAll("input,select").forEach(input=>{
    options[input.name] = input.value;
  });

  const data = new FormData();
  data.append("tool",current.id);
  data.append("options",JSON.stringify(options));
  files.forEach(file=>data.append("files",file));

  busy = true;
  const controls = Array.from(
    document.querySelectorAll("#form input,#form select,#form button,.tool")
  );
  controls.forEach(control=>control.disabled=true);
  $("status").textContent = "Processing… Please wait.";

  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),180000);

  try{
    const response = await fetch("/api/process",{
      method:"POST",body:data,signal:controller.signal
    });

    if(!response.ok){
      const error = await response.json().catch(()=>({}));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "Request failed: " + response.status
      );
    }

    const blob = await response.blob();
    resultURL = URL.createObjectURL(blob);

    const header = response.headers.get("Content-Disposition") || "";
    const filename = header.match(/filename="([^"]+)"/);

    $("download").href = resultURL;
    $("download").download = filename ? filename[1] : "result";
    $("download").hidden = false;

    $("status").className = "success";
    $("status").textContent =
      `Done! Output: ${(blob.size/1048576).toFixed(2)} MB`;
  }catch(error){
    $("status").className = "error";
    $("status").textContent = error.name === "AbortError"
      ? "Request timeout. Chhoti file try karein."
      : error.message;
  }finally{
    clearTimeout(timer);
    busy = false;
    controls.forEach(control=>control.disabled=false);
  }
};

selectTool(tools[0]);
</script>
</body>
</html>
"""


# ===================== HELPERS =====================

def fail(message):
    raise ValueError(message)


def number(value, minimum, maximum):
    try:
        result = int(value)
    except (ValueError, TypeError):
        fail("Invalid numeric value.")
    if not minimum <= result <= maximum:
        fail(f"Value {minimum} se {maximum} ke beech honi chahiye.")
    return result


def open_pdf(data, password=""):
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception:
        fail("Invalid, damaged ya unsupported PDF.")

    if document.needs_pass and not document.authenticate(password):
        document.close()
        fail("Correct existing PDF password enter karein.")

    if not 1 <= document.page_count <= MAX_PAGES:
        document.close()
        fail(f"PDF mein 1–{MAX_PAGES} pages allowed hain.")

    return document


def page_selection(spec, count):
    spec = str(spec).strip()

    if not spec:
        return list(range(count))

    result = []

    try:
        for part in spec.split(","):
            part = part.strip()

            if "-" in part:
                start, end = map(int, part.split("-", 1))
            else:
                start = end = int(part)

            if not 1 <= start <= end <= count:
                raise ValueError()

            if len(result) + end - start + 1 > MAX_PAGES:
                raise ValueError()

            result.extend(range(start - 1, end))

    except (ValueError, TypeError):
        fail("Invalid page range. Example: 1-3,5.")

    if not result:
        fail("Kam se kam ek page select karein.")

    return result


def save_pdf(document):
    return document.tobytes(
        garbage=4,
        deflate=True,
        encryption=fitz.PDF_ENCRYPT_NONE,
    )


def load_image(data):
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                fail("Sirf JPG, PNG aur WebP supported hain.")

            if source.width * source.height > MAX_PIXELS:
                fail("Maximum image size 20 megapixels hai.")

            # Animated images: process the first frame only.
            source.seek(0)
            result = ImageOps.exif_transpose(source).convert("RGBA")

        return result

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        fail("Invalid image ya image dimensions bahut badi hain.")


def white_background(image):
    output = Image.new("RGB", image.size, "white")
    output.paste(image, mask=image.getchannel("A"))
    return output


# ===================== TOOL PROCESSING =====================

def process(tool, uploads, options):
    password = str(options.get("input_password", ""))

    if tool == "merge":
        if len(uploads) < 2:
            fail("Merge ke liye kam se kam 2 PDFs select karein.")

        with fitz.open() as output:
            for data in uploads:
                with open_pdf(data, password) as source:
                    if output.page_count + source.page_count > MAX_PAGES:
                        fail(f"Combined PDF limit {MAX_PAGES} pages hai.")
                    output.insert_pdf(source)

            return save_pdf(output), "merged.pdf", "application/pdf"

    if tool == "images-to-pdf":
        with fitz.open() as output:
            for data in uploads:
                with load_image(data) as image:
                    with white_background(image) as rgb:
                        stream = io.BytesIO()
                        rgb.save(stream, format="JPEG", quality=90)

                    page = output.new_page(width=595, height=842)
                    page.insert_image(
                        fitz.Rect(24, 24, 571, 818),
                        stream=stream.getvalue(),
                        keep_proportion=True,
                    )

            return save_pdf(output), "images.pdf", "application/pdf"

    if len(uploads) != 1:
        fail("Is tool ke liye sirf ek file select karein.")

    if tool in {"image-convert", "image-resize"}:
        with load_image(uploads[0]) as image:
            if tool == "image-resize":
                width = number(options.get("width", 1200), 1, 8000)
                height = number(options.get("height", 1200), 1, 8000)

                # Downsize only; preserve aspect ratio.
                image.thumbnail(
                    (width, height),
                    Image.Resampling.LANCZOS,
                )

            extension = str(options.get("format", "png")).lower()

            formats = {
                "png": ("PNG", "image/png"),
                "jpg": ("JPEG", "image/jpeg"),
                "webp": ("WEBP", "image/webp"),
            }

            if extension not in formats:
                fail("Invalid image output format.")

            output_format, mime = formats[extension]
            buffer = io.BytesIO()

            if extension == "jpg":
                with white_background(image) as rgb:
                    rgb.save(buffer, output_format, quality=90)
            elif extension == "webp":
                image.save(buffer, output_format, quality=90)
            else:
                image.save(buffer, output_format, optimize=True)

            return buffer.getvalue(), f"image.{extension}", mime

    pdf_tools = {
        "extract",
        "rotate",
        "compress",
        "lock",
        "unlock",
        "pdf-to-images",
        "pdf-to-text",
        "watermark",
        "numbers",
    }

    if tool not in pdf_tools:
        fail("Unknown tool.")

    with open_pdf(uploads[0], password) as document:
        if tool == "extract":
            pages = page_selection(
                options.get("pages", ""),
                document.page_count,
            )

            with fitz.open() as output:
                for index in pages:
                    output.insert_pdf(
                        document,
                        from_page=index,
                        to_page=index,
                    )

                return save_pdf(output), "extracted.pdf", "application/pdf"

        if tool == "rotate":
            angle = number(options.get("angle", 90), 90, 270)

            if angle not in {90, 180, 270}:
                fail("Rotation 90, 180 ya 270 honi chahiye.")

            pages = page_selection(
                options.get("pages", ""),
                document.page_count,
            )

            for index in set(pages):
                page = document[index]
                page.set_rotation((page.rotation + angle) % 360)

        elif tool == "lock":
            new_password = str(options.get("password", ""))

            if not 1 <= len(new_password.encode("utf-8")) <= 40:
                fail("New password 1–40 UTF-8 bytes ka hona chahiye.")

            result = document.tobytes(
                garbage=4,
                deflate=True,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=new_password,
                owner_pw=secrets.token_hex(20),
                permissions=(
                    fitz.PDF_PERM_PRINT
                    | fitz.PDF_PERM_COPY
                    | fitz.PDF_PERM_ANNOTATE
                ),
            )

            return result, "protected.pdf", "application/pdf"

        elif tool == "pdf-to-text":
            result = "\n\n".join(
                f"--- Page {index + 1} ---\n{page.get_text()}"
                for index, page in enumerate(document)
            )

            return (
                result.encode("utf-8"),
                "extracted.txt",
                "text/plain; charset=utf-8",
            )

        elif tool == "pdf-to-images":
            pages = page_selection(
                options.get("pages", ""),
                document.page_count,
            )

            if len(pages) > 50:
                fail("Ek request mein maximum 50 pages render karein.")

            dpi = number(options.get("dpi", 120), 72, 144)
            buffer = io.BytesIO()
            total = 0

            with zipfile.ZipFile(
                buffer,
                "w",
                compression=zipfile.ZIP_STORED,
            ) as archive:
                for position, index in enumerate(pages):
                    page = document[index]
                    pixels = (
                        page.rect.width
                        * page.rect.height
                        * (dpi / 72) ** 2
                    )

                    if pixels > MAX_PIXELS:
                        fail("Page dimensions bahut badi hain.")

                    pixmap = page.get_pixmap(
                        dpi=dpi,
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )

                    png = pixmap.tobytes("png")
                    total += len(png)

                    if total > MAX_OUTPUT:
                        fail("Output 60 MB se bada hai. Kam pages select karein.")

                    archive.writestr(
                        f"{position + 1:03d}-page-{index + 1}.png",
                        png,
                    )

            return (
                buffer.getvalue(),
                "pdf-images.zip",
                "application/zip",
            )

        elif tool == "watermark":
            text = str(options.get("text", "CONFIDENTIAL")).strip()

            if not text or len(text) > 80:
                fail("Watermark 1–80 characters ka hona chahiye.")

            if any(ord(char) < 32 or ord(char) > 126 for char in text):
                fail("Watermark ke liye English letters/numbers use karein.")

            for page in document:
                if page.rotation:
                    page.remove_rotation()

                text_width = max(
                    fitz.get_text_length(text, fontsize=1),
                    1,
                )
                font_size = min(
                    42,
                    page.rect.width * 0.8 / text_width,
                    page.rect.height * 0.2,
                )
                x = (page.rect.width - text_width * font_size) / 2

                page.insert_text(
                    (x, page.rect.height / 2),
                    text,
                    fontsize=font_size,
                    color=(0.5, 0.5, 0.5),
                    fill_opacity=0.22,
                    overlay=True,
                )

        elif tool == "numbers":
            for index, page in enumerate(document):
                if page.rotation:
                    page.remove_rotation()

                text = f"{index + 1} / {document.page_count}"
                font_size = min(
                    10,
                    page.rect.width / 20,
                    page.rect.height / 10,
                )
                text_width = fitz.get_text_length(
                    text,
                    fontsize=font_size,
                )

                page.insert_text(
                    (
                        max(0, (page.rect.width - text_width) / 2),
                        page.rect.height - font_size,
                    ),
                    text,
                    fontsize=font_size,
                    color=(0.35, 0.35, 0.35),
                    overlay=True,
                )

        # Compress: lossless cleanup.
        # Unlock: authenticated PDF saved without encryption.
        result = save_pdf(document)

        if tool == "compress":
            # Keep original if an unencrypted input was already smaller.
            with fitz.open(
                stream=uploads[0],
                filetype="pdf",
            ) as original:
                if (
                    not original.needs_pass
                    and not original.is_encrypted
                    and len(uploads[0]) < len(result)
                ):
                    result = uploads[0]

        return result, f"{tool}.pdf", "application/pdf"


# ===================== ROUTES =====================

@app.get("/", response_class=HTMLResponse)
def homepage():
    return HTMLResponse(
        HTML,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/process")
def api_process(
    tool: str = Form(...),
    options: str = Form("{}"),
    files: list[UploadFile] = File(...),
):
    try:
        if not 1 <= len(files) <= 20:
            fail("1–20 files allowed.")

        if len(options) > 4096:
            fail("Options bahut bade hain.")

        try:
            settings = json.loads(options)
        except json.JSONDecodeError:
            fail("Invalid options.")

        if not isinstance(settings, dict):
            fail("Options object hona chahiye.")

        # Protect processing memory and serialize PyMuPDF calls.
        if not PROCESS_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=503,
                detail="Server busy hai. Thodi der baad try karein.",
            )

        try:
            uploads = []
            total = 0

            for upload in files:
                content = upload.file.read(MAX_UPLOAD - total + 1)
                total += len(content)

                if total > MAX_UPLOAD:
                    fail("Maximum total upload size 40 MB.")

                if not content:
                    fail("Empty files allowed nahi hain.")

                uploads.append(content)

            content, filename, mime = process(
                tool,
                uploads,
                settings,
            )

            if len(content) > MAX_OUTPUT:
                fail("Output 60 MB se bada hai. Chhoti file try karein.")

        finally:
            PROCESS_LOCK.release()

        return Response(
            content=content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except HTTPException:
        raise

    except Exception:
        logging.exception("Processing failed")
        raise HTTPException(
            status_code=500,
            detail="File process nahi ho saki. File damaged ya unsupported ho sakti hai.",
        )

    finally:
        for upload in files:
            upload.file.close()


# ===================== START SERVER =====================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        limit_concurrency=12,
    )
