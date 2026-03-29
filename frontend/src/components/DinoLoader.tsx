interface DinoLoaderProps {
  message?: string;
}

export default function DinoLoader({ message = "引擎轰鸣转录中，请先喝杯水..." }: DinoLoaderProps) {
  return (
    <div className="flex flex-col items-center justify-center p-8">
      <img
        src="/dino.gif"
        alt="loading"
        className="w-48 rounded-lg"
      />
      <p className="text-center text-slate-500 text-sm mt-3">{message}</p>
    </div>
  );
}
