import React from "react";
import { useNavigate } from "react-router-dom";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function EmptyState({ title, hint, actionLabel = "Go to ECR analysis", to = "/analyze" }) {
  const navigate = useNavigate();
  return (
    <div className="surface flex flex-col items-center justify-center gap-3 p-12 text-center">
      <div className="grid h-11 w-11 place-items-center rounded-xl bg-secondary/70">
        <Compass className="h-5 w-5 text-muted-foreground" />
      </div>
      <div>
        <div className="text-sm font-semibold">{title}</div>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <Button size="sm" variant="outline" onClick={() => navigate(to)}>
        {actionLabel}
      </Button>
    </div>
  );
}
