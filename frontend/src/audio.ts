function downsample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) out[i] = input[Math.floor(i * ratio)];
  return out;
}

function toPcm16(input: Float32Array): ArrayBuffer {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return out.buffer;
}

export class CallAudio {
  private ctx: AudioContext | null = null;
  private nextTime = 0;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;

  async startMic(send: (pcm: ArrayBuffer) => void): Promise<void> {
    this.ctx = new AudioContext();
    await this.ctx.resume();
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const rate = this.ctx.sampleRate;
    this.processor.onaudioprocess = (event) => {
      const channel = event.inputBuffer.getChannelData(0);
      send(toPcm16(downsample(channel, rate, 24000)));
    };
    const silent = this.ctx.createGain();
    silent.gain.value = 0;
    source.connect(this.processor);
    this.processor.connect(silent);
    silent.connect(this.ctx.destination);
  }

  play(pcm: ArrayBuffer): void {
    if (!this.ctx) return;
    const samples = new Int16Array(pcm);
    const floats = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i += 1) floats[i] = samples[i] / 32768;
    const buffer = this.ctx.createBuffer(1, floats.length, 24000);
    buffer.copyToChannel(floats, 0);
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    const now = this.ctx.currentTime;
    if (this.nextTime < now) this.nextTime = now + 0.05;
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
  }

  stop(): void {
    this.processor?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.ctx?.close();
    this.processor = null;
    this.stream = null;
    this.ctx = null;
    this.nextTime = 0;
  }
}
