"""Colour the existing transparent alpha artwork using the shared action token.

The SVG filter preserves the original image's geometry and transparent gaps.
It does not redraw or modify the original, white cutout, header or favicon.
"""
import base64
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
colour = re.search(r'--action:(#[0-9A-Fa-f]{6})', (root / 'static/style.css').read_text(encoding='utf-8')).group(1)
encoded = base64.b64encode((root / 'static/company-logo-transparent.png').read_bytes()).decode('ascii')
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1672" height="941" viewBox="0 0 1672 941">
  <defs><filter id="forest-green" color-interpolation-filters="sRGB"><feFlood flood-color="{colour}"/><feComposite in2="SourceAlpha" operator="in"/></filter></defs>
  <image width="1672" height="941" href="data:image/png;base64,{encoded}" filter="url(#forest-green)"/>
</svg>
'''
(root / 'static/company-logo-green.svg').write_text(svg, encoding='utf-8')
print('Saved forest green login copy; original artwork and favicon unchanged.')
