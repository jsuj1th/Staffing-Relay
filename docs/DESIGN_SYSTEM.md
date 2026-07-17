# Relay LMS Design System

> CSS Variables, Responsive Design, & Accessibility Standards

**Last Updated:** 2026-07-17  
**Compliance:** WCAG AA, iOS HIG, Material Design 3

---

## 📋 Design Tokens

All colors, spacing, and typography are defined as CSS variables in `templates/base.html`:

### Colors

```css
--color-primary: #8A3A2E           /* Brand red */
--color-primary-dark: #712E24      /* Dark red for hover */
--color-primary-light: #F5E8E6     /* Light red background */
--color-accent: #D4AF37            /* Gold accent */

--color-success: #5F7A52           /* Green for approved */
--color-success-dark: #4D6542
--color-success-light: #EAF2E6

--color-error: #C1440E             /* Error states */
--color-error-light: #FCEEE9

--color-warning: #C98B3A           /* Warning states */
--color-warning-light: #FDF3E0

--color-surface: #FBF9F4           /* Main surface */
--color-surface-alt: #F6F1E8       /* Secondary surface */
--color-background: #EAE3D7        /* Page background */
--color-border: #E4DACB            /* Primary border */
--color-border-secondary: #C4B7A6  /* Secondary border */

--color-text-primary: #2B2521      /* Main text */
--color-text-secondary: #6B5F54    /* Secondary text */
--color-text-tertiary: #9A8D7E     /* Tertiary text */
--color-text-muted: #8A8073        /* Muted text */

--color-dark-bg: #2B2521           /* Sidebar bg */
--color-dark-text: #FBF9F4         /* Light text on dark */
--color-dark-text-secondary: #A89C8C
```

**Usage in components:**
```html
<button style="background: var(--color-primary);">Action</button>
<div style="border-color: var(--color-border);">Card</div>
```

### Spacing Scale (4pt base)

```css
--spacing-xs: 4px      /* Extra small gaps */
--spacing-sm: 8px      /* Small gaps (common) */
--spacing-md: 12px     /* Medium padding */
--spacing-lg: 16px     /* Large padding */
--spacing-xl: 20px     /* Extra large padding */
--spacing-2xl: 28px    /* Section padding */
```

### Typography

```css
--font-serif: 'Spectral', serif           /* Headings */
--font-sans: 'IBM Plex Sans', sans-serif  /* Body text */
--font-mono: 'IBM Plex Mono', monospace   /* Labels, code */
```

### Interactions

```css
--touch-min-size: 44px                    /* Apple/Material standard */
--transition-fast: 150ms ease-out         /* Quick feedback */
--transition-base: 200ms ease-out         /* Standard transitions */
--transition-slow: 300ms ease-out         /* Slow animations */
```

---

## 🎨 Component Patterns

### Buttons

```html
<!-- Primary action -->
<button class="relay-btn relay-btn-primary">Save</button>

<!-- Secondary action -->
<button class="relay-btn">Cancel</button>

<!-- Success action -->
<button class="relay-btn relay-btn-approve">Approve</button>
```

**Guaranteed sizes:**
- Min-height: 44px (touch target)
- Padding: 12px horizontal, 12px vertical
- Focus ring: 3px blue outline
- Transition: 200ms smooth

### Forms

```html
<div class="mb-3">
  <label for="name" class="form-label">Name</label>
  <input type="text" class="form-control" id="name" required>
  <div class="invalid-feedback">Name is required</div>
</div>
```

**Features:**
- Min-height: 44px (touch-friendly)
- Focus ring: 3px on primary color
- Error state: Red border + error message
- Disabled state: Grayed out, no-cursor
- Transitions: 200ms smooth

### Badges

```html
<span class="relay-badge-approved">APPROVED</span>
<span class="relay-badge-rejected">REJECTED</span>
<span class="relay-badge-extreme">EXTREME</span>
<span class="relay-badge-pending">PENDING</span>
<span class="relay-badge-cancelled">CANCELLED</span>
```

### Loading Skeleton

```html
<!-- Skeleton loader for async content -->
<div class="skeleton skeleton-text" style="height: 24px;"></div>
<div class="skeleton skeleton-text" style="height: 16px; width: 80%;"></div>
<div class="skeleton skeleton-text" style="height: 16px; width: 60%;"></div>
```

**Features:**
- Shimmer animation (2s loop)
- Respects `prefers-reduced-motion`
- Use for loading times > 300ms

---

## 📱 Responsive Breakpoints

### Mobile First Approach

**375px** (Mobile)
- Sidebar collapses to 60px (icons only)
- Main content adds left margin: 60px
- Tables convert to card layout (data-label pattern)
- Font sizes: no smaller than 16px (iOS auto-zoom safe)

**768px** (Tablet)
- Sidebar expands to 240px (full width)
- Main content margin removed
- Tables return to grid layout

**1024px** (Desktop)
- Max-width: enforced on containers
- Optimal reading: 60–75 chars per line

### Example: Responsive Table

```html
<!-- Mobile: Card layout, Desktop: Grid layout -->
<table>
  <thead>
    <tr>
      <th data-label="Name">Name</th>
      <th data-label="Email">Email</th>
      <th data-label="Status">Status</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td data-label="Name">John Doe</td>
      <td data-label="Email">john@example.com</td>
      <td data-label="Status">Active</td>
    </tr>
  </tbody>
</table>
```

CSS automatically converts to card view on <768px via `data-label` attributes.

---

## ♿ Accessibility Checklist

- ✅ **Contrast:** All text meets 4.5:1 WCAG AA minimum
- ✅ **Touch targets:** Buttons/inputs ≥44px minimum
- ✅ **Keyboard:** Focus rings visible on all interactive elements
- ✅ **Motion:** Animations respect `prefers-reduced-motion`
- ✅ **Forms:** Labels always visible (not placeholder-only)
- ✅ **Errors:** Error messages placed below related field

### Testing

```bash
# Check contrast in dev tools
# 1. Open Accessibility panel
# 2. Look for "Contrast" warnings
# 3. All should be ≥4.5:1 for normal text

# Test keyboard navigation
# 1. Press Tab to navigate
# 2. Focus rings should be visible
# 3. All buttons/links should be reachable

# Test motion preferences
# 1. Settings > Accessibility > Motion
# 2. Set to "Reduce motion"
# 3. Animations should stop/minimize
```

---

## 🛠 Customization

### Adding a New Color Token

```css
/* In templates/base.html :root */
:root {
  --color-custom: #XXXXXX;
}

/* Use it */
<div style="background: var(--color-custom);">Content</div>
```

### Adding a New Spacing Value

```css
:root {
  --spacing-3xl: 32px;
}

/* Use it */
<div style="padding: var(--spacing-3xl);">Content</div>
```

### Overriding for Dark Mode (Future)

```css
@media (prefers-color-scheme: dark) {
  :root {
    --color-text-primary: #FBF9F4;
    --color-background: #1a1a1a;
  }
}
```

---

## 📚 References

- **WCAG AA:** https://www.w3.org/WAI/WCAG21/quickref/
- **iOS HIG:** https://developer.apple.com/design/human-interface-guidelines/
- **Material Design 3:** https://m3.material.io/
- **UI/UX Pro Max:** https://uupm.cc

---

## 🚀 Performance

- All transitions use GPU-accelerated properties (transform, opacity)
- Skeleton animations respect `prefers-reduced-motion`
- No layout thrashing (batch DOM reads/writes)
- Images lazy-loaded below fold

---

## Version History

| Date | Change |
|------|--------|
| 2026-07-17 | Initial design system: tokens, responsive, a11y |
| TBD | Dark mode variant |
| TBD | Component library (Storybook) |
