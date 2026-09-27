function reorderProjects(current,source,target,after=false){
 const projects=[...current.projects];
 if(source===target||!projects.includes(source)||!projects.includes(target))return null;
 projects.splice(projects.indexOf(source),1);
 projects.splice(projects.indexOf(target)+(after?1:0),0,source);
 const pinned=current.pinnedProjects.filter(id=>id!==source);
 if(current.pinnedProjects.includes(target))pinned.push(source);
 return {projects,projectGroups:{...current.projectGroups,[source]:current.projectGroups[target]||''},pinnedProjects:pinned};
}
