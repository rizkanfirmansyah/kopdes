---
name: Technical Precision
colors:
  surface: '#0f1416'
  surface-dim: '#0f1416'
  surface-bright: '#343a3b'
  surface-container-lowest: '#090f10'
  surface-container-low: '#171d1e'
  surface-container: '#1b2122'
  surface-container-high: '#252b2c'
  surface-container-highest: '#303637'
  on-surface: '#dee3e5'
  on-surface-variant: '#bcc9cc'
  inverse-surface: '#dee3e5'
  inverse-on-surface: '#2b3133'
  outline: '#869396'
  outline-variant: '#3d494b'
  surface-tint: '#55d7ed'
  primary: '#55d7ed'
  on-primary: '#00363e'
  primary-container: '#00acc1'
  on-primary-container: '#003a42'
  inverse-primary: '#006876'
  secondary: '#f9abff'
  on-secondary: '#570066'
  secondary-container: '#86039c'
  on-secondary-container: '#f7a0ff'
  tertiary: '#ffb875'
  on-tertiary: '#4b2800'
  tertiary-container: '#da8a36'
  on-tertiary-container: '#502b00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#9eefff'
  primary-fixed-dim: '#55d7ed'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004e59'
  secondary-fixed: '#ffd6fe'
  secondary-fixed-dim: '#f9abff'
  on-secondary-fixed: '#35003f'
  on-secondary-fixed-variant: '#7b008f'
  tertiary-fixed: '#ffdcc0'
  tertiary-fixed-dim: '#ffb875'
  on-tertiary-fixed: '#2d1600'
  on-tertiary-fixed-variant: '#6b3b00'
  background: '#0f1416'
  on-background: '#dee3e5'
  surface-variant: '#303637'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: -0.01em
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  panel-padding: 20px
---

## Brand & Style

This design system is engineered for utility, stability, and professional efficiency. It targets network administrators and developers who require high-density information without visual fatigue. 

The aesthetic is rooted in **Corporate Minimalism** with a **Technical** edge. It prioritizes functional hierarchy and "glanceable" data metrics. By using a dark, low-contrast foundation paired with high-chroma status indicators, the system ensures that critical system events remain the primary focus. The interface avoids decorative flourishes like glassmorphism or heavy gradients, instead relying on strict alignment, subtle borders, and intentional use of negative space to create a premium, "built-for-work" atmosphere.

## Colors

The palette is designed for prolonged use in low-light environments. The **Dark Charcoal** background provides the deepest layer, while **Surface Panels** create a secondary elevation for interactive modules.

- **Primary Cyan:** Used for primary actions, active states, and selection highlights.
- **Secondary Purple:** Reserved for system-level utilities and specific data visualizations (e.g., system load).
- **Functional Semantics:** Red, Amber, and Green are used strictly for status reporting (Failed, Warning, Active). Use these sparingly to maintain their urgency.
- **Borders:** A consistent #2A2A2A stroke is used to define container boundaries without introducing high-contrast visual noise.

## Typography

The system employs a dual-font strategy to distinguish between UI navigation and technical data.

1. **UI Sans-Serif (Inter):** Used for all structural elements, titles, and button labels. It provides high legibility and a modern, neutral tone.
2. **Technical Mono (JetBrains Mono):** Used exclusively for terminal output, IP addresses, ports, logs, and any variable-driven data. This ensures characters like '0' and 'O' are easily distinguishable and maintains vertical alignment in data tables.

For mobile or narrow-sidebar views, reduce `headline-lg` to 20px (`headline-md`) to prevent excessive wrapping.

## Layout & Spacing

This design system utilizes a **Fixed Grid** approach for the main dashboard dashboard with a 12-column structure, transitioning to a fluid stack on mobile devices.

- **Dashboard Layout:** Standardized 20px padding within all panels. 
- **Information Density:** Use 8px (sm) spacing for related items within a component (e.g., a label and its input) and 16px (md) for spacing between distinct components.
- **Responsive Behavior:** 
  - **Desktop (>1024px):** 12 columns, fixed sidebars.
  - **Tablet (768px - 1023px):** 8 columns, collapsible sidebars.
  - **Mobile (<767px):** Single column, 16px horizontal margins.

## Elevation & Depth

Depth is achieved through **Tonal Layering** rather than traditional shadows. This keeps the UI feeling flat and fast.

- **Level 0 (Background):** #121212 - The canvas.
- **Level 1 (Panels):** #1E1E1E - Used for cards and secondary content areas. 
- **Level 2 (Modals/Popovers):** #252525 - Used for floating elements. These are the only elements allowed a subtle, 15% opacity black shadow (blur: 10px) to assist with focus.
- **Active State:** Elements like selected menu items use a subtle left-hand border accent (2px) in the Primary Cyan color to indicate focus.

## Shapes

The shape language is disciplined. A "Rounded" (8px - 12px) radius is applied to panels and large buttons to soften the technical nature of the app without appearing "bubbly."

- **Standard Radius:** 8px for buttons, input fields, and small cards.
- **Large Radius (rounded-lg):** 12px for main dashboard containers and modals.
- **Full Radius (rounded-full):** Used only for status badges and toggle switches.

## Components

### Buttons
- **Primary:** Filled Primary Cyan (#00ACC1) with #121212 text. No gradient.
- **Secondary:** Transparent with a 1px #2A2A2A border. Text in white (87% opacity).
- **Danger:** Ghost style with red text, shifting to a solid red background on hover.

### Input Fields
- Dark grey background (#181818) with a 1px border (#2A2A2A). 
- Active/Focus state: Border changes to Primary Cyan. 
- Use JetBrains Mono for inputs containing technical values (Ports, IPs).

### Chips & Badges
- Used for connection status (Active, Failed, Idle).
- Format: Small, pill-shaped, with a subtle 10% opacity background of the status color and a solid text color.

### Data Tables
- Row height: 48px.
- Use zebra stripping with #1E1E1E and #1A1A1A for readability.
- Header row: `label-caps` typography with 1px bottom border.

### Connection Inspector
- A dedicated side or bottom panel with #1E1E1E background. 
- Technical logs within this component should use a pure black background (#000000) to simulate a terminal environment.