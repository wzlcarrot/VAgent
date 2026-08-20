/** 登录页角色看向鼠标的几何计算（与 DOM 解耦，便于单测）。 */

export function calcFaceOffset(
  cx: number,
  cy: number,
  mouseX: number,
  mouseY: number,
): { faceX: number; faceY: number; bodySkew: number } {
  const dx = mouseX - cx
  const dy = mouseY - cy
  const faceX = Math.max(-15, Math.min(15, dx / 20))
  const faceY = Math.max(-10, Math.min(10, dy / 30))
  const bodySkew = Math.max(-6, Math.min(6, -dx / 120))
  return { faceX: faceX + 0, faceY: faceY + 0, bodySkew: bodySkew + 0 }
}

export function calcPupilOffset(
  cx: number,
  cy: number,
  mouseX: number,
  mouseY: number,
  maxDist: number,
): { x: number; y: number } {
  const dx = mouseX - cx
  const dy = mouseY - cy
  const dist = Math.min(Math.sqrt(dx * dx + dy * dy), maxDist)
  const angle = Math.atan2(dy, dx)
  return { x: Math.cos(angle) * dist, y: Math.sin(angle) * dist }
}

export function rectCenter(rect: { left: number; width: number; top: number; height: number }, yFactor = 0.5) {
  return {
    cx: rect.left + rect.width / 2,
    cy: rect.top + rect.height * yFactor,
  }
}
