#ifndef SNESRECOMP_BEAM_FRAME_DRIVER_H
#define SNESRECOMP_BEAM_FRAME_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

/* Beam-aligned frame driver for whole-program LLE ports.
 *
 * One host frame is one PPU field, cut where hardware raises NMI: the beam's
 * vblank edge (V=225). The CPU half runs the guest against the real beam,
 * taking every interrupt where it latches -- raster H/V matches and a
 * coprocessor holding the IRQ line (SuperFX, Cx4, SA-1) -- and lets hardware
 * time pass while the guest is parked, so the beam, APU and coprocessors get
 * the whole field. The render half rasterizes that field from the raster
 * journal (ppu.c), stepping the real HDMA unit per line.
 *
 * new_project scaffolds call these from src/game_rtl.c; a title replaces
 * them only when it needs something they do not do (see
 * docs/FRAME_MODEL_HOSTS.md). */

void snes_beam_frame_driver_run_frame(void);
void snes_beam_frame_driver_draw_ppu_frame(void);
/* Observe the display state that actually produced each visible line, after
 * raster journal writes and before H-blank HDMA. The PPU is read-only and the
 * callback must not advance the machine or change guest memory/registers.
 * `line` is 1..224, corresponding to output row line-1. No observer is kept
 * between calls; the regular draw entry point is identical to passing NULL. */
struct Ppu;
typedef void SnesBeamRasterObserver(const struct Ppu *ppu, unsigned line, void *context);
void snes_beam_frame_driver_draw_ppu_frame_observed(
    SnesBeamRasterObserver *observer, void *context);
/* Forget the booted machine: the next frame starts from the reset vector. */
void snes_beam_frame_driver_reset(void);

/* The driver's own execution position, for save states.
 *
 * A guest snapshot (snes_saveload) holds the machine, not where the driver
 * resumes it: the PC the next slice re-enters the guest at (0 = not booted,
 * which makes the next frame start from the reset vector) and the WAI halt
 * latch. Both are host statics, so a state loaded into a fresh process --
 * where the PC is still 0 -- rebooted the game on top of the restored RAM,
 * and one loaded into a running process resumed at whatever PC that process
 * had parked on. A title that saves states writes this next to the guest
 * blob (state_save_extra, with RtlSaveExecutionState for g_cpu and the
 * bridge) and puts it back in on_state_loaded. Plain data, no pointers. */
typedef struct SnesBeamFrameDriverState {
  uint32_t resume_pc;  /* 24-bit PC; 0 = boot from the reset vector */
  uint8_t wai_halted;
  uint8_t pad[3];
} SnesBeamFrameDriverState;
void snes_beam_frame_driver_get_state(SnesBeamFrameDriverState *out);
void snes_beam_frame_driver_set_state(const SnesBeamFrameDriverState *in);
/* Lagless pacing, a diagnostic mode (0 = off, the default). When the CPU half
 * meets the field's V=225 edge while still working, the field is held and the
 * CPU runs on until it waits (stable poll or WAI), for at most max_fields more
 * fields; the NMI is then taken at the next frame's start, where the CPU waits.
 * Every game step thus gets exactly one NMI however long it computes, so two
 * execution models that charge different cycles for the same work stay in
 * step frame for frame. Used by differential co-simulation; it is not the
 * hardware's timing (a real console drops frames: lag). */
void snes_beam_frame_driver_set_lagless(int max_fields);
/* Lagless pacing: whether a CPU that the field edge cut at resume_pc24 was
 * waiting -- a poll the interpreter has not recognised as a stable state (a
 * loop whose flags or registers change while it polls), or a compiled
 * spin-wait. The port knows its wait primitives; NULL (the default) counts
 * only interpreter-detected stable polls and WAI. Returns the wait loop's
 * head (0: not a wait). An NMI taken while the CPU waits there returns to
 * the head, whatever loop instruction each side stopped on: a handler that
 * records the interrupted PC (Romancing SaGa 3's battle NMI saves it in RAM
 * to hijack its RTI) then sees the same one on both sides. */
typedef uint32_t SnesBeamWaitHint(uint32_t resume_pc24);
void snes_beam_frame_driver_set_wait_hint(SnesBeamWaitHint *hint);

#endif /* SNESRECOMP_BEAM_FRAME_DRIVER_H */
