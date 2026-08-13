export async function copyTextToClipboard(value: string): Promise<void> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Clipboard permission may still be denied on HTTPS. Continue with the
      // selection-based fallback also used by plain HTTP VPS deployments.
    }
  }

  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, value.length);

  try {
    if (!document.execCommand("copy")) {
      throw new Error("Browser rejected clipboard copy");
    }
  } finally {
    textarea.remove();
    previousFocus?.focus({ preventScroll: true });
  }
}
