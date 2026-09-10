import { useCallback, useEffect, useId, useRef } from 'react';
import { CloseIcon } from './DashboardIcons.jsx';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Dialog shell. The admin screen previously hand-rolled this and got only
 * backdrop-click dismissal — no Escape, no focus trap, no role, and focus was
 * left stranded on a button that had unmounted. This adds all of that in one
 * place so any future dialog inherits it.
 *
 * The backdrop closes on click, but only when the click *started* on the
 * backdrop: dragging a text selection out of the dialog used to dismiss it and
 * lose whatever had been typed.
 */
export default function Modal({ title, description, onClose, children, labelledBy }) {
  const dialogRef = useRef(null);
  const restoreRef = useRef(null);
  const pressedBackdrop = useRef(false);
  const generatedId = useId();
  const titleId = labelledBy || generatedId;

  const focusables = useCallback(
    () => Array.from(dialogRef.current?.querySelectorAll(FOCUSABLE) || []),
    [],
  );

  // Remember what had focus so it can be handed back on close.
  useEffect(() => {
    restoreRef.current = document.activeElement;
    const first = focusables()[0];
    (first || dialogRef.current)?.focus();
    return () => restoreRef.current?.focus?.();
  }, [focusables]);

  // Escape to dismiss, Tab cycles inside the dialog.
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      const items = focusables();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [onClose, focusables]);

  // Stop the page behind the dialog from scrolling.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        pressedBackdrop.current = e.target === e.currentTarget;
      }}
      onMouseUp={(e) => {
        if (pressedBackdrop.current && e.target === e.currentTarget) onClose();
        pressedBackdrop.current = false;
      }}
    >
      <div
        className="modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
      >
        <div className="modal__header">
          <div>
            <h3 id={titleId}>{title}</h3>
            {description && <p className="muted modal__description">{description}</p>}
          </div>
          <button
            type="button"
            className="modal__close"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <CloseIcon />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
