import React from "react";

function SectionCard({ as: Tag = "section", className = "", children, ...props }) {
  return (
    <Tag {...props} className={["section-card", className].filter(Boolean).join(" ")}>
      {children}
    </Tag>
  );
}

export default SectionCard;
