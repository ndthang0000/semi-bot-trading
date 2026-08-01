import TiptapImage from "@tiptap/extension-image";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold,
  Heading2,
  Heading3,
  ImagePlus,
  Italic,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  RemoveFormatting,
  Strikethrough,
  Underline,
  Undo2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

const MAX_IMAGE_SOURCE_BYTES = 10 * 1024 * 1024;
const MAX_EMBEDDED_IMAGE_LENGTH = 1_200_000;
const MAX_IMAGE_SIDE = 1_600;

export function RichTextEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (html: string) => void;
}) {
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [imageBusy, setImageBusy] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const editor = useEditor({
    extensions: [
      StarterKit,
      TiptapImage.configure({
        allowBase64: true,
        HTMLAttributes: { class: "journal-inline-image" },
      }),
    ],
    content: value,
    editorProps: {
      attributes: {
        class: "min-h-[460px] px-5 py-4 text-sm leading-7 text-slate-200 outline-none",
        "aria-label": "Nội dung nhật ký tuần",
      },
    },
    onUpdate: ({ editor: currentEditor }) => onChange(currentEditor.getHTML()),
  });
  // React StrictMode intentionally mounts and tears down the editor twice in
  // development. Never call Tiptap APIs through the stale destroyed instance.
  const readyEditor = editor && !editor.isDestroyed ? editor : null;

  useEffect(() => {
    if (!editor || editor.isDestroyed || editor.getHTML() === value) return;
    editor.commands.setContent(value, { emitUpdate: false });
  }, [editor, value]);

  async function insertImage(file: File | undefined) {
    if (!file || !readyEditor) return;
    setImageBusy(true);
    setImageError(null);
    try {
      const src = await compressJournalImage(file);
      readyEditor.chain().focus().setImage({ src, alt: file.name, title: file.name }).run();
    } catch (error) {
      setImageError(error instanceof Error ? error.message : "Không thể chèn ảnh.");
    } finally {
      setImageBusy(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  }

  return (
    <div className="weekly-rich-editor overflow-hidden rounded-xl border border-ink-700 bg-ink-950 focus-within:border-cyan-500/60">
      <div className="flex flex-wrap gap-1 border-b border-ink-700 bg-ink-900 p-2">
        <ToolbarButton label="Bold" active={readyEditor?.isActive("bold")} onClick={() => readyEditor?.chain().focus().toggleBold().run()}>
          <Bold size={15} />
        </ToolbarButton>
        <ToolbarButton label="Italic" active={readyEditor?.isActive("italic")} onClick={() => readyEditor?.chain().focus().toggleItalic().run()}>
          <Italic size={15} />
        </ToolbarButton>
        <ToolbarButton label="Underline" active={readyEditor?.isActive("underline")} onClick={() => readyEditor?.chain().focus().toggleUnderline().run()}>
          <Underline size={15} />
        </ToolbarButton>
        <ToolbarButton label="Strikethrough" active={readyEditor?.isActive("strike")} onClick={() => readyEditor?.chain().focus().toggleStrike().run()}>
          <Strikethrough size={15} />
        </ToolbarButton>
        <ToolbarDivider />
        <ToolbarButton label="Heading 2" active={readyEditor?.isActive("heading", { level: 2 })} onClick={() => readyEditor?.chain().focus().toggleHeading({ level: 2 }).run()}>
          <Heading2 size={16} />
        </ToolbarButton>
        <ToolbarButton label="Heading 3" active={readyEditor?.isActive("heading", { level: 3 })} onClick={() => readyEditor?.chain().focus().toggleHeading({ level: 3 }).run()}>
          <Heading3 size={16} />
        </ToolbarButton>
        <ToolbarDivider />
        <ToolbarButton label="Bullet list" active={readyEditor?.isActive("bulletList")} onClick={() => readyEditor?.chain().focus().toggleBulletList().run()}>
          <List size={16} />
        </ToolbarButton>
        <ToolbarButton label="Numbered list" active={readyEditor?.isActive("orderedList")} onClick={() => readyEditor?.chain().focus().toggleOrderedList().run()}>
          <ListOrdered size={16} />
        </ToolbarButton>
        <ToolbarButton label="Quote" active={readyEditor?.isActive("blockquote")} onClick={() => readyEditor?.chain().focus().toggleBlockquote().run()}>
          <Quote size={16} />
        </ToolbarButton>
        <ToolbarButton label="Divider" onClick={() => readyEditor?.chain().focus().setHorizontalRule().run()}>
          <Minus size={16} />
        </ToolbarButton>
        <ToolbarButton label={imageBusy ? "Đang xử lý ảnh" : "Chèn ảnh"} disabled={imageBusy || !readyEditor} onClick={() => imageInputRef.current?.click()}>
          <ImagePlus size={16} />
        </ToolbarButton>
        <input
          ref={imageInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(event) => void insertImage(event.target.files?.[0])}
          aria-label="Chọn ảnh chèn vào nhật ký"
        />
        <ToolbarDivider />
        <ToolbarButton label="Clear formatting" onClick={() => readyEditor?.chain().focus().clearNodes().unsetAllMarks().run()}>
          <RemoveFormatting size={16} />
        </ToolbarButton>
        <ToolbarButton label="Undo" disabled={!readyEditor?.can().chain().focus().undo().run()} onClick={() => readyEditor?.chain().focus().undo().run()}>
          <Undo2 size={16} />
        </ToolbarButton>
        <ToolbarButton label="Redo" disabled={!readyEditor?.can().chain().focus().redo().run()} onClick={() => readyEditor?.chain().focus().redo().run()}>
          <Redo2 size={16} />
        </ToolbarButton>
      </div>
      {imageError && <div className="border-b border-red-500/20 bg-red-500/5 px-4 py-2 text-xs text-red-300">{imageError}</div>}
      <EditorContent editor={readyEditor} />
    </div>
  );
}

async function compressJournalImage(file: File): Promise<string> {
  if (!new Set(["image/png", "image/jpeg", "image/webp"]).has(file.type)) {
    throw new Error("Chỉ hỗ trợ ảnh PNG, JPEG hoặc WebP.");
  }
  if (file.size > MAX_IMAGE_SOURCE_BYTES) {
    throw new Error("Ảnh gốc vượt quá 10MB.");
  }
  const source = await readFileAsDataUrl(file);
  const image = await loadImage(source);
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Trình duyệt không thể xử lý ảnh này.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  for (const quality of [0.84, 0.72, 0.6]) {
    const output = canvas.toDataURL("image/webp", quality);
    if (output.length <= MAX_EMBEDDED_IMAGE_LENGTH) return output;
  }
  throw new Error("Ảnh vẫn quá lớn sau khi nén. Hãy chọn ảnh nhỏ hơn.");
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Không thể đọc file ảnh."));
    reader.readAsDataURL(file);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("File ảnh không hợp lệ."));
    image.src = src;
  });
}

function ToolbarButton({
  label,
  active = false,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={[
        "grid h-8 w-8 place-items-center rounded-md border text-slate-400 transition-colors",
        active
          ? "border-cyan-400/50 bg-cyan-500/15 text-cyan-200"
          : "border-transparent hover:border-ink-700 hover:bg-ink-950 hover:text-slate-200",
        disabled ? "cursor-not-allowed opacity-30" : "",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function ToolbarDivider() {
  return <div className="mx-1 h-8 w-px bg-ink-700" aria-hidden="true" />;
}
