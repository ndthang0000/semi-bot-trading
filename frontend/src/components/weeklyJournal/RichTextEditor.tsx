import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold,
  Heading2,
  Heading3,
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
import { useEffect } from "react";

export function RichTextEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (html: string) => void;
}) {
  const editor = useEditor({
    extensions: [StarterKit],
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
      <EditorContent editor={readyEditor} />
    </div>
  );
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
