import os

path = r'c:\Users\dell\Downloads\Hackathon\self-healing-cicd\healing-engine\agents\orchestrator_agent.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """            return Incident(
                job_name=job_name,
                build_number=build_number,
                classification=classification,
                error_class=error_class,
                final_fix=None,  # cached fix in metadata
                final_confidence=int(cached["similarity"] * 100),
                resolution_mode=ResolutionMode.CACHED,
                agents_used=agents_used,
                total_tokens_used=0,
                processing_time_seconds=elapsed,
            )"""

new_block = """            from models.schemas import FixResult, RootCauseAnalysis
            import json
            
            cached_fix = FixResult(
                fix_description=cached.get("fix", "Cached fix retrieved"),
                fix_code=cached.get("fix_code", ""),
                fix_steps=["Apply the cached fix code"],
                confidence=int(cached["similarity"] * 100)
            )
            
            cached_root_cause = RootCauseAnalysis(
                root_cause=cached.get("root_cause", "Cached root cause"),
                error_category=error_class,
                severity=cached.get("metadata", {}).get("severity", "MEDIUM") if isinstance(cached.get("metadata"), dict) else "MEDIUM"
            )

            incident = Incident(
                job_name=job_name,
                build_number=build_number,
                classification=classification,
                error_class=error_class,
                root_cause=cached_root_cause,
                final_fix=cached_fix,
                final_confidence=int(cached["similarity"] * 100),
                resolution_mode=ResolutionMode.CACHED,
                agents_used=agents_used,
                total_tokens_used=0,
                processing_time_seconds=elapsed,
            )

            logger.info("[ORCHESTRATOR] Step 8 (Cached): Notify Agent")
            agents_used.append("Notify")
            await self.notify_agent.run(incident)

            return incident"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully replaced!")
else:
    print("Error: Old block not found.")
