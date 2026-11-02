import { useState } from "react";
import { ArrowUpRight, FileText, Image as ImageIcon } from "lucide-react";
import { t } from "../i18n";
import type { Artifact } from "../model";
import {
  evidenceImageUrl,
  IMAGE_PREVIEW_LIMIT,
  isImageEvidence,
  type ImageEvidence,
} from "../image-evidence";
import "./evidence-media.css";

export function EvidenceThumbnail({
  projectId,
  artifact,
  className = "",
}: {
  projectId: string;
  artifact: Artifact;
  className?: string;
}) {
  const src = evidenceImageUrl(projectId, artifact);
  const [failed, setFailed] = useState<string | null>(null);
  const unavailable = failed === src || artifact.bytes > IMAGE_PREVIEW_LIMIT;
  return (
    <span className={`evidence-thumbnail ${className}`}>
      {unavailable ? (
        <span className="image-unavailable">
          <ImageIcon size={18} />
          <span>{t("预览不可用")}</span>
        </span>
      ) : (
        <img
          src={src}
          alt={artifact.title}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(src)}
        />
      )}
    </span>
  );
}

export function NodeFigure({
  projectId,
  images,
  onOpen,
}: {
  projectId: string;
  images: ImageEvidence[];
  onOpen: (artifact: Artifact) => void;
}) {
  const image = images[0];
  if (!image) return null;
  return (
    <button
      className="node-figure nodrag nopan"
      aria-label={t("查看图片：{title}", { title: image.artifact.title })}
      title={
        image.inherited
          ? `${image.ownerTitle} · ${image.artifact.title}`
          : image.artifact.title
      }
      onClick={(event) => {
        event.stopPropagation();
        onOpen(image.artifact);
      }}
    >
      <EvidenceThumbnail projectId={projectId} artifact={image.artifact} />
      <span className="node-figure-caption">
        <ImageIcon size={11} />
        <span>{image.inherited ? image.ownerTitle : image.artifact.title}</span>
        {images.length > 1 && <b>+{images.length - 1}</b>}
        <ArrowUpRight size={11} />
      </span>
    </button>
  );
}

export function EvidenceRow({
  projectId,
  artifact,
  onOpen,
}: {
  projectId: string;
  artifact: Artifact;
  onOpen: (artifact: Artifact) => void;
}) {
  const image = isImageEvidence(artifact);
  return (
    <button
      className={`artifact-row ${image ? "has-image" : ""}`}
      onClick={() => onOpen(artifact)}
    >
      {image ? (
        <EvidenceThumbnail projectId={projectId} artifact={artifact} />
      ) : (
        <FileText size={17} />
      )}
      <span>
        <strong>{artifact.title}</strong>
        <small>
          {image ? `${t("图片")} · ` : ""}
          {artifact.bytes.toLocaleString()} bytes · {artifact.mime}
        </small>
      </span>
      <ArrowUpRight size={13} />
    </button>
  );
}
