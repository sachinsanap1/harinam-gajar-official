// Scroll progress for the paavul (footstep) trail
window.addEventListener("scroll", () => {
  const trail = document.getElementById("paavul-trail");
  if (!trail) return;
  const scrolled = window.scrollY;
  const height = document.documentElement.scrollHeight - window.innerHeight;
  const pct = height > 0 ? (scrolled / height) * 100 : 0;
  trail.style.setProperty("--scroll-progress", pct + "%");
});
