declare module "@office-kit/pptx" {
  export type PresentationData = object;
  export type SlideData = object;

  export function loadPresentation(
    data: ArrayBuffer | Uint8Array,
  ): Promise<PresentationData>;

  export function getSlides(presentation: PresentationData): SlideData[];
}
