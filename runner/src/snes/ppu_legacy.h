#pragma once

#include "ppu.h"

/*
 * Compatibility scanline renderer.
 *
 * Selection belongs to Ppu::renderFlags; game hosts should never provide a
 * parallel renderer-selection global. This declaration stays private to the
 * PPU implementation even though the legacy renderer has its own translation
 * unit.
 */
void ppu_draw_whole_line_legacy(Ppu *ppu, int line);
/* True when the line the legacy renderer draws produces 512 distinct columns
 * (modes 5/6 or pseudo-hires). With a hi-res surface bound
 * (PpuBindHiresSurface) such a line writes both dots of every pair there. */
bool ppu_legacy_line_is_hires(const Ppu *ppu);
