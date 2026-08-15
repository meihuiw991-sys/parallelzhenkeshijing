class PCM16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sourceSamples = [];
    this.sourcePosition = 0;
    this.outputSamples = [];
    this.ratio = sampleRate / 16000;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.sourceSamples.push(channel[index]);
    }

    while (this.sourcePosition + 1 < this.sourceSamples.length) {
      const lower = Math.floor(this.sourcePosition);
      const fraction = this.sourcePosition - lower;
      const sample = this.sourceSamples[lower] * (1 - fraction) + this.sourceSamples[lower + 1] * fraction;
      this.outputSamples.push(Math.max(-1, Math.min(1, sample)));
      this.sourcePosition += this.ratio;

      if (this.outputSamples.length === 1600) {
        const pcm = new Int16Array(1600);
        for (let index = 0; index < pcm.length; index += 1) {
          const value = this.outputSamples[index];
          pcm[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
        }
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
        this.outputSamples = [];
      }
    }

    const consumed = Math.floor(this.sourcePosition);
    if (consumed > 0) {
      this.sourceSamples.splice(0, consumed);
      this.sourcePosition -= consumed;
    }
    return true;
  }
}

registerProcessor("pcm16-capture", PCM16CaptureProcessor);
