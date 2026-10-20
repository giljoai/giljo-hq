/**
 * BE-9797: the Jobs board reads every card's agents with one
 * `agentJobs.listMany(ids)` call. Specs that model the server one project at a
 * time derive that reply from their per-project `list` mock, the way the server
 * does: the union of each project's jobs, each carrying its `project_id`.
 */
export async function listManyFrom(listOne, ids) {
  const replies = await Promise.all(ids.map(async (id) => [id, await listOne(id)]))
  const jobs = replies.flatMap(([id, reply]) =>
    reply.data.jobs.map((job) => ({ ...job, project_id: id })),
  )
  return { data: { jobs, total: jobs.length, limit: 500, offset: 0 } }
}
