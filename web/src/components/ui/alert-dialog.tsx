"use client"

import * as React from "react"
import { AlertDialog as AlertDialogPrimitive } from "radix-ui"

/**
 * `design.md` §4's registry gains one part: `keep-dialog` (`spec-ingredient-keep.md` §2).
 *
 * **Thin wrappers, and no Tailwind recipe.** The other files in this folder came from `shadcn add`
 * and carry its utility classes; this one is written here because the dialog it serves is drawn in
 * the product's own ink/paper vocabulary (`preferences.css`), and a second set of colours arriving
 * through a component default is exactly the styled-by-accident failure §0 exists to prevent. What
 * these add over the Radix primitives is the `data-slot` convention the rest of the folder uses,
 * and nothing else — focus trapping, `Esc`, the backdrop and the ARIA roles are Radix's and are the
 * reason this is not a hand-rolled `<div>`.
 *
 * **Never `window.confirm`.** A native dialog blocks the page's own event loop and every automation
 * pointed at it, including the evaluator's browser at the gate — so the check would have no way to
 * read the copy it is gating.
 */
function AlertDialog(props: React.ComponentProps<typeof AlertDialogPrimitive.Root>) {
  return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />
}

function AlertDialogPortal(props: React.ComponentProps<typeof AlertDialogPrimitive.Portal>) {
  return <AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />
}

function AlertDialogOverlay(props: React.ComponentProps<typeof AlertDialogPrimitive.Overlay>) {
  return <AlertDialogPrimitive.Overlay data-slot="alert-dialog-overlay" {...props} />
}

function AlertDialogContent(props: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  return <AlertDialogPrimitive.Content data-slot="alert-dialog-content" {...props} />
}

function AlertDialogTitle(props: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return <AlertDialogPrimitive.Title data-slot="alert-dialog-title" {...props} />
}

function AlertDialogDescription(
  props: React.ComponentProps<typeof AlertDialogPrimitive.Description>,
) {
  return <AlertDialogPrimitive.Description data-slot="alert-dialog-description" {...props} />
}

function AlertDialogAction(props: React.ComponentProps<typeof AlertDialogPrimitive.Action>) {
  return <AlertDialogPrimitive.Action data-slot="alert-dialog-action" {...props} />
}

function AlertDialogCancel(props: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
  return <AlertDialogPrimitive.Cancel data-slot="alert-dialog-cancel" {...props} />
}

export {
  AlertDialog,
  AlertDialogPortal,
  AlertDialogOverlay,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
}
